"""A refusal comes back under the names the request used, not the model's.

A service raises about the model, because the model is what it was handed. The
request may have called those fields something else -- a serializer field
declares ``source=`` precisely to let the two diverge -- and DRF resolves
``source=`` while building ``validated_data``, at every depth, so by the time
the service runs the wire name is gone from the payload entirely. The
``SerializerValidator`` is the one thing still holding both vocabularies.

These assert, over a kernel spec served by a view, that the rename reaches
every depth and that it leaves alone what it cannot name.

The kernel route does not rename yet: ``answering_refusals`` is not told which
serializer the call validated with, and the kernel route has no step renaming a
refusal by a serializer's ``source=``. Every test that needs the rename is a
strict ``xfail`` naming that, so the day the edge hands its validator's
serializer over and renames by it, they fail as XPASS until the marks come off.
"""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import ServiceSpec, ServiceValidationError, Unrestricted
from django_service_specs.mutations.create_from_input import create_from_input
from django_service_specs.relations.child_spec import ChildSpec
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory

from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Catalog, Section
from tests.views.test_kernel_views import _CreateView

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)

# One reason, so the marks read as one gap and come off together.
_NOT_RENAMED = pytest.mark.xfail(
    strict=True,
    reason=(
        "the kernel route answers a service's refusal under the model's names: the edge does "
        "not hand answering_refusals the validator's serializer, and no step on the kernel "
        "route renames a refusal by a serializer's source="
    ),
)


class _AuthorInput(serializers.Serializer):
    some_name = serializers.CharField(source="name")


class _SectionInput(serializers.Serializer):
    heading = serializers.CharField(source="title")


class _PostInput(serializers.Serializer):
    headline = serializers.CharField(source="title")
    writer = _AuthorInput(source="author")


class _CatalogInput(serializers.Serializer):
    name = serializers.CharField()
    chapters = _SectionInput(source="sections", many=True)


def _refuse(detail: Any, error: type[Exception] = ServiceValidationError) -> Any:
    """A service that refuses with ``detail``, in model vocabulary."""

    def service(**_: Any) -> None:
        raise error(detail)

    return service


def _spec(
    service: Any, serializer: type[serializers.Serializer] | None = _PostInput, **kw: Any
) -> Any:
    validator = None if serializer is None else SerializerValidator(serializer)
    return ServiceSpec(service=service, permissions=_OPEN, validator=validator, **kw)


def _served(spec: Any, body: Any) -> Any:
    view = type("_View", (_CreateView,), {"spec": spec}).as_view()
    response = view(factory.post("/x/", body, format="json"))
    response.render()
    return response


_PAYLOAD: dict[str, Any] = {"headline": "t", "writer": {"some_name": "x"}}


class TestTheRenameReachesEveryDepth:
    @_NOT_RENAMED
    def test_a_top_level_field_takes_its_wire_name(self) -> None:
        response = _served(_spec(_refuse({"title": ["Too long."]})), _PAYLOAD)

        assert response.status_code == 400
        assert response.data == {"headline": ["Too long."]}

    @_NOT_RENAMED
    def test_a_nested_field_takes_its_own(self) -> None:
        """The half a relation-level alias could never reach."""
        response = _served(_spec(_refuse({"author": {"name": ["Too short."]}})), _PAYLOAD)

        assert response.data == {"writer": {"some_name": ["Too short."]}}

    @_NOT_RENAMED
    def test_a_collection_is_renamed_without_losing_its_alignment(self) -> None:
        spec = _spec(_refuse({"sections": [{}, {"title": ["Too rude."]}]}), _CatalogInput)

        response = _served(spec, {"name": "c", "chapters": [{"heading": "a"}, {"heading": "b"}]})

        assert response.data == {"chapters": [{}, {"heading": ["Too rude."]}]}

    @_NOT_RENAMED
    def test_a_collection_keyed_by_index_is_renamed_inside_its_rows(self) -> None:
        # DRF's other form for a collection, and the one it defaults to from
        # 3.18: an ``int`` key is a row's position, never a field, so the row
        # beneath it is named by the same serializer the list form's rows are.
        spec = _spec(_refuse({"sections": {1: {"title": ["Too rude."]}}}), _CatalogInput)

        response = _served(spec, {"name": "c", "chapters": [{"heading": "a"}, {"heading": "b"}]})

        assert response.content == b'{"chapters":{"1":{"heading":["Too rude."]}}}'

    @_NOT_RENAMED
    def test_it_meets_a_real_nested_write(self) -> None:
        """End to end: the relation spec names the model, the caller sees the wire."""

        def service(*, data: Any) -> Any:
            return create_from_input(
                Catalog,
                data,
                relations={
                    "sections": ChildSpec(
                        model=Section,
                        fk="catalog",
                        create_service=_refuse({"title": ["Too rude."]}),
                    )
                },
            ).instance

        response = _served(
            _spec(service, _CatalogInput), {"name": "c", "chapters": [{"heading": "a"}]}
        )

        assert response.content == b'{"chapters":{"0":{"heading":["Too rude."]}}}'


class TestWhatItLeavesAlone:
    @_NOT_RENAMED
    def test_a_key_the_serializer_does_not_know(self) -> None:
        """Renaming what it can name means never guessing at what it cannot."""
        detail = {"non_field_errors": ["Nope."], "title": ["Too long."]}

        response = _served(_spec(_refuse(detail)), _PAYLOAD)

        assert response.data == {"non_field_errors": ["Nope."], "headline": ["Too long."]}

    def test_a_detail_that_is_not_a_field_map(self) -> None:
        """A service may raise a string; there is no field name in it to rename."""
        response = _served(_spec(_refuse("Nope.")), _PAYLOAD)

        assert response.status_code == 400
        assert response.data == ["Nope."]

    @_NOT_RENAMED
    def test_a_list_of_messages_under_a_renamed_key(self) -> None:
        """The key is renamed; the messages under it are not walked into."""
        response = _served(_spec(_refuse({"author": ["Unavailable."]})), _PAYLOAD)

        assert response.data == {"writer": ["Unavailable."]}

    def test_a_spec_with_no_validator(self) -> None:
        """No second vocabulary, so nothing to translate between."""
        response = _served(_spec(_refuse({"title": ["Too long."]}), None), {})

        assert response.data == {"title": ["Too long."]}

    def test_a_service_that_does_not_raise(self) -> None:
        response = _served(_spec(lambda **_: None), _PAYLOAD)

        assert response.status_code == 204

    def test_an_author_can_still_reach_the_model_name(self) -> None:
        """The escape hatch: a serializer that does not alias renames nothing."""

        class _Plain(serializers.Serializer):
            title = serializers.CharField()

        response = _served(_spec(_refuse({"title": ["Too long."]}), _Plain), {"title": "t"})

        assert response.data == {"title": ["Too long."]}


class TestEveryErrorClassAndBothCores:
    @_NOT_RENAMED
    def test_drf_s_own_error_class_is_preserved(self) -> None:
        response = _served(_spec(_refuse({"title": ["Too long."]}, ValidationError)), _PAYLOAD)

        assert response.status_code == 400
        assert response.data == {"headline": ["Too long."]}

    @_NOT_RENAMED
    def test_a_precondition_is_renamed_too(self) -> None:
        """Preconditions speak about the input, so they owe the same names."""

        def refuse_precondition(**_: Any) -> None:
            raise ServiceValidationError({"title": ["Locked."]})

        spec = _spec(lambda **_: None, preconditions=[refuse_precondition])

        assert _served(spec, _PAYLOAD).data == {"headline": ["Locked."]}


class TestTheBulkPath:
    @_NOT_RENAMED
    def test_a_many_dispatch_renames_through_the_child(self) -> None:
        spec = _spec(_refuse([{}, {"title": ["Too long."]}]), many=True)

        response = _served(spec, [_PAYLOAD, _PAYLOAD])

        assert response.data == [{}, {"headline": ["Too long."]}]
