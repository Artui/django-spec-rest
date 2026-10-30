"""A ``many`` spec's refusal of its rows is a tree keyed by the argument, its rows by index.

The kernel refuses the list under the argument that carries it (``items``, or
the spec's ``many_argument``) and each invalid row under its ``int`` index, a
valid row having no entry. DRF below 3.18 reports a list with an empty entry
per valid row and 3.18 a mapping of the invalid rows' indexes; both reach a
client as the latter. The tree is the dual-base ``DRFInvalidArguments``, so it is
DRF's ``ValidationError`` too, and renders as JSON with the indexes as string
keys.

A refusal of a read beside the rows keeps its own key beside the argument's
rather than being unwrapped into a bare list.

**Client-visible changes.** A drfs ``many`` view answered three things differently, and
the tests assert the kernel's answer for each:

* A refusal of the rows was the bare tree, ``{"1": {...}, "3": {...}}``; the kernel
  answers it under the argument, ``{"items": {"1": {...}}}``.
* A body that was no list was ``{"non_field_errors": ["Expected a list of items but
  got type \"dict\"."]}``; the kernel answers ``{"items": ["Expected an array."]}``.
* A body that is a list holding a row that is no object was
  ``{"1": {"non_field_errors": ["Invalid data. Expected a dictionary, but got
  str."]}}``; the kernel answers ``{"items": {"1": {"non_field_errors": ["Expected an
  object."]}}}``.

Unwrapping the first two to the drfs shape would need the spec inside
``answering_refusals``. The third is the kernel's own wording for a row that is no
object, against DRF's; the bulk body as a whole is awaiting an owner decision
(the kernel's wording and nesting, or DRF's), and until it is made the tests pin the
kernel's answer.
"""

from __future__ import annotations

from collections.abc import Callable
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

from django_spec_rest.service_specs.drf_invalid_arguments import DRFInvalidArguments
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.views.test_kernel_edge import CORES, _parts
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


def _refusal(core: Callable[..., Any], spec: ServiceSpec, rows: Any) -> DRFInvalidArguments:
    with pytest.raises(DRFInvalidArguments) as caught:
        core(spec, **_parts(rows))
    return caught.value


def _served(spec: ServiceSpec, rows: Any) -> Any:
    view = type("_View", (_CreateView,), {"spec": spec}).as_view()
    response = view(factory.post("/", rows, format="json"))
    response.render()
    return response


@CORES
def test_item_errors_are_keyed_by_the_invalid_items_index(core: Callable[..., Any]) -> None:
    refusal = _refusal(core, _spec(), [_GOOD, _BAD, _GOOD, _BAD])

    assert refusal.detail == {"items": {1: _BAD_DETAIL, 3: _BAD_DETAIL}}
    detail: Any = refusal.detail
    assert all(isinstance(index, int) for index in detail["items"])


@CORES
def test_item_errors_reported_as_a_list_are_keyed_by_index_too(core: Callable[..., Any]) -> None:
    refusal = _refusal(core, _spec(_LineReportedAsAList), [_GOOD, _BAD, _GOOD, _BAD])

    assert refusal.detail == {"items": {1: _BAD_DETAIL, 3: _BAD_DETAIL}}
    assert refusal.get_codes() == {"items": {1: {"sku": ["blank"]}, 3: {"sku": ["blank"]}}}


@CORES
def test_every_item_invalid_is_keyed_from_zero(core: Callable[..., Any]) -> None:
    refusal = _refusal(core, _spec(), [_BAD, _BAD])

    assert refusal.detail == {"items": {0: _BAD_DETAIL, 1: _BAD_DETAIL}}


@CORES
def test_item_errors_keep_their_codes(core: Callable[..., Any]) -> None:
    refusal = _refusal(core, _spec(), [_GOOD, _BAD])

    assert refusal.get_codes() == {"items": {1: {"sku": ["blank"]}}}


@CORES
def test_a_mistyped_item_is_refused_at_its_index(core: Callable[..., Any]) -> None:
    refusal = _refusal(core, _spec(), [_GOOD, {"sku": "a", "quantity": "many"}])

    assert refusal.detail == {"items": {1: {"quantity": ["Expected an integer."]}}}


@CORES
def test_the_declared_argument_names_the_refusal(core: Callable[..., Any]) -> None:
    refusal = _refusal(core, _spec(many_argument="lines"), [_GOOD, _BAD])

    assert refusal.detail == {"lines": {1: _BAD_DETAIL}}


@CORES
def test_a_refusal_beside_the_rows_keeps_its_key(core: Callable[..., Any]) -> None:
    """Only a refusal of the rows alone has the rows' key, and a read beside them has its own."""
    spec = _spec(_Line, _rows_of_an_author, reads=Parameters.of(Parameter("author_pk", "integer")))

    refusal = _refusal(core, spec, [_GOOD])

    assert isinstance(refusal.detail, dict)
    assert list(refusal.detail) == ["author_pk"]


@CORES
def test_item_errors_answer_before_a_read_beside_the_list(core: Callable[..., Any]) -> None:
    spec = _spec(_Line, _rows_of_an_author, reads=Parameters.of(Parameter("author_pk", "integer")))

    refusal = _refusal(core, spec, [_BAD])

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
