from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import (
    Parameter,
    Parameters,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory

from django_spec_rest.dispatch.kernel_edge import dispatch_kernel_spec
from django_spec_rest.service_specs.drf_invalid_arguments import DRFInvalidArguments
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.views.test_kernel_edge import _parts
from tests.views.test_kernel_views import _CreateView

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_GOOD: dict[str, Any] = {"sku": "a", "quantity": 1}
_BAD: dict[str, Any] = {"sku": "", "quantity": 1}
_BAD_DETAIL = {"sku": ["This field may not be blank."]}


class _Line(serializers.Serializer):
    sku = serializers.CharField()
    quantity = serializers.IntegerField()


class _ItemErrorsAsAList(serializers.ListSerializer):
    """Reports item errors as DRF below 3.18 does, in DRF 3.14's own loop: a list with
    an empty entry for every valid item. The locked DRF never produces that shape, so
    without this the normalisation would be held only by the floor job."""

    def to_internal_value(self, data: Any) -> Any:
        child: Any = self.child
        ret: list[Any] = []
        errors: list[Any] = []
        for item in data:
            try:
                validated = child.run_validation(item)
            except ValidationError as exc:
                errors.append(exc.detail)
            else:
                ret.append(validated)
                errors.append({})
        if any(errors):
            raise ValidationError(errors)
        return ret


class _LineReportedAsAList(_Line):
    class Meta:
        list_serializer_class = _ItemErrorsAsAList


def _rows(*, data: Any) -> Any:
    return data


def _rows_of_an_author(*, data: Any, author_pk: int) -> Any:
    return data


def _spec(
    line: type[serializers.Serializer] = _Line, service: Any = _rows, **kwargs: Any
) -> ServiceSpec:
    return ServiceSpec(
        service=service,
        permissions=_OPEN,
        many=True,
        validator=SerializerValidator(line),
        **kwargs,
    )


def _refusal(spec: ServiceSpec, rows: Any) -> DRFInvalidArguments:
    with pytest.raises(DRFInvalidArguments) as caught:
        dispatch_kernel_spec(spec, **_parts(rows))
    return caught.value


def _served(spec: ServiceSpec, rows: Any) -> Any:
    view = type("_View", (_CreateView,), {"spec": spec}).as_view()
    response = view(factory.post("/", rows, format="json"))
    response.render()
    return response


def test_item_errors_are_keyed_by_the_invalid_items_index() -> None:
    refusal = _refusal(_spec(), [_GOOD, _BAD, _GOOD, _BAD])

    assert refusal.detail == {"items": {1: _BAD_DETAIL, 3: _BAD_DETAIL}}
    detail: Any = refusal.detail
    assert all(isinstance(index, int) for index in detail["items"])


def test_item_errors_reported_as_a_list_are_keyed_by_index_too() -> None:
    refusal = _refusal(_spec(_LineReportedAsAList), [_GOOD, _BAD, _GOOD, _BAD])

    assert refusal.detail == {"items": {1: _BAD_DETAIL, 3: _BAD_DETAIL}}
    assert refusal.get_codes() == {"items": {1: {"sku": ["blank"]}, 3: {"sku": ["blank"]}}}


def test_every_item_invalid_is_keyed_from_zero() -> None:
    refusal = _refusal(_spec(), [_BAD, _BAD])

    assert refusal.detail == {"items": {0: _BAD_DETAIL, 1: _BAD_DETAIL}}


def test_item_errors_keep_their_codes() -> None:
    refusal = _refusal(_spec(), [_GOOD, _BAD])

    assert refusal.get_codes() == {"items": {1: {"sku": ["blank"]}}}


def test_a_mistyped_item_is_refused_at_its_index() -> None:
    refusal = _refusal(_spec(), [_GOOD, {"sku": "a", "quantity": "many"}])

    assert refusal.detail == {"items": {1: {"quantity": ["Expected an integer."]}}}


def test_the_declared_argument_names_the_refusal() -> None:
    refusal = _refusal(_spec(many_argument="lines"), [_GOOD, _BAD])

    assert refusal.detail == {"lines": {1: _BAD_DETAIL}}


def test_a_refusal_beside_the_rows_keeps_its_key() -> None:
    """Only a refusal of the rows alone has the rows' key, and a read beside them has its own."""
    spec = _spec(_Line, _rows_of_an_author, reads=Parameters.of(Parameter("author_pk", "integer")))

    refusal = _refusal(spec, [_GOOD])

    assert isinstance(refusal.detail, dict)
    assert list(refusal.detail) == ["author_pk"]


def test_item_errors_answer_before_a_read_beside_the_list() -> None:
    spec = _spec(_Line, _rows_of_an_author, reads=Parameters.of(Parameter("author_pk", "integer")))

    refusal = _refusal(spec, [_BAD])

    assert refusal.detail == {"items": {0: _BAD_DETAIL}}


def test_over_a_view_the_indexes_are_json_keys() -> None:
    response = _served(_spec(), [_GOOD, _BAD, _GOOD, _BAD])

    assert response.status_code == 400
    assert response.content == (
        b'{"items":{"1":{"sku":["This field may not be blank."]},'
        b'"3":{"sku":["This field may not be blank."]}}}'
    )


def test_over_a_view_a_list_body_that_is_no_list_is_refused_under_the_argument() -> None:
    response = _served(_spec(), {"sku": "a"})

    assert response.status_code == 400
    assert response.data == {"items": ["Expected an array."]}


def test_over_a_view_a_row_that_is_no_object_is_refused_at_its_index() -> None:
    response = _served(_spec(), [_GOOD, "x"])

    assert response.status_code == 400
    assert response.content == b'{"items":{"1":{"non_field_errors":["Expected an object."]}}}'
