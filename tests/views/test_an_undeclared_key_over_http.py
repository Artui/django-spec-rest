"""What the HTTP edge's ``IGNORE`` makes of a key no parameter declares, past a flat body.

The edge dispatches under ``IGNORE``, so the kernel drops a key no parameter declares, as
DRF drops a key no serializer field declares. These are the shapes where that drop is not
the whole story: a bulk row, an update's body naming another row, and a form body whose
nested and list fields DRF spells as prefixed keys.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.db.models import QuerySet
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView, ServiceUpdateView
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _Title(serializers.Serializer):
    title = serializers.CharField()


def test_a_bulk_row_s_undeclared_key_is_dropped_from_that_row_alone() -> None:
    received: list[Any] = []
    spec = ServiceSpec(
        service=lambda *, data: received.append(data),
        permissions=_OPEN,
        validator=SerializerValidator(_Title),
        many=True,
        atomic=False,
    )
    view = type("_View", (ServiceCreateView,), {"spec": spec}).as_view()
    response = view(factory.post("/", [{"title": "a", "nope": 1}, {"title": "b"}], format="json"))
    # The service returns nothing, so there is nothing to present.
    assert response.status_code == 204, response.data
    assert received == [[{"title": "a"}, {"title": "b"}]]


class _Name(serializers.Serializer):
    name = serializers.CharField()


def _author_by_pk(pk: int) -> QuerySet[Author]:
    return Author.objects.filter(pk=pk)


def _rename(*, instance: Author, data: dict[str, Any]) -> Author:
    instance.name = data["name"]
    instance.save()
    return instance


def test_an_update_body_naming_another_row_s_id_changes_the_route_s_row_alone() -> None:
    """A client sending a row back carries its ``id``; dropped, it chooses nothing."""
    routed = Author.objects.create(name="routed")
    other = Author.objects.create(name="other")
    spec = ServiceSpec(
        service=_rename,
        permissions=_OPEN,
        validator=SerializerValidator(_Name),
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=_author_by_pk,
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
        ),
    )
    view = type("_View", (ServiceUpdateView,), {"spec": spec, "permission_classes": []})
    request = factory.put(f"/{routed.pk}/", {"name": "x", "id": other.pk}, format="json")
    response = view.as_view()(request, pk=routed.pk)
    assert response.status_code == 200, response.data
    routed.refresh_from_db()
    other.refresh_from_db()
    assert (routed.name, other.name) == ("x", "other")


class _Inner(serializers.Serializer):
    tenant = serializers.CharField()


class _Nested(serializers.Serializer):
    title = serializers.CharField()
    v = _Inner(required=False)
    tags = serializers.ListField(child=serializers.CharField(), required=False)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "the flat reader takes a form body's keys as sent, so DRF's prefixed spellings of a "
        "nested or list field (v.tenant, tags[0]) are keys no parameter declares, and the "
        "edge's IGNORE drops them: the client gets a 2xx and the field's value is lost, "
        "where DRF builds the nested dict and the list from them"
    ),
)
@pytest.mark.parametrize(
    ("body", "field", "value"),
    [
        ({"title": "t", "v.tenant": "x"}, "v", {"tenant": "x"}),
        ({"title": "t", "tags[0]": "a"}, "tags", ["a"]),
    ],
    ids=["nested", "list"],
)
def test_a_form_body_s_prefixed_key_reaches_its_field(
    body: dict[str, Any], field: str, value: Any
) -> None:
    received: list[dict[str, Any]] = []
    spec = ServiceSpec(
        service=lambda *, data: received.append(data),
        permissions=_OPEN,
        validator=SerializerValidator(_Nested),
    )
    view = type("_View", (ServiceCreateView,), {"spec": spec}).as_view()
    response = view(factory.post("/", body, format="multipart"))
    assert response.status_code == 204, response.data
    assert received == [{"title": "t", field: value}]
