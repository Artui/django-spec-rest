"""A kernel write spec's target on a viewset is its own target selector's.

The viewset's ``get_object()`` and its ``"retrieve"`` entry are never asked for
a kernel write's row: the spec's ``instance_selector_spec`` (or
``collection_selector_spec``) finds it inside the kernel's dispatch, and the
view's object permission is asked of what it finds.
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
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceViewSet
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_BY_PK = Parameters.of(Parameter("pk", "integer", required=True))


class _NameIn(serializers.Serializer):
    name = serializers.CharField()


def _by_pk(**fields: Any) -> SelectorSpec:
    defaults: dict[str, Any] = {
        "selector": lambda *, pk: Author.objects.filter(pk=pk).first(),
        "reads": _BY_PK,
    }
    return SelectorSpec(kind=SelectorKind.RETRIEVE, **{**defaults, **fields})


def _rename(*, instance: Author, data: dict[str, Any]) -> Author:
    instance.name = data["name"]
    instance.save(update_fields=["name"])
    return instance


def _delete(*, instance: Author) -> None:
    instance.delete()


_UPDATE = ServiceSpec(
    service=_rename,
    permissions=_OPEN,
    validator=SerializerValidator(_NameIn),
    presenter=SerializerPresenter(AuthorSerializer),
    instance_selector_spec=_by_pk(),
)
_DESTROY = ServiceSpec(service=_delete, permissions=_OPEN, instance_selector_spec=_by_pk())


class _ViewSet(ServiceViewSet):
    queryset = Author.objects.none()
    action_specs = {"update": _UPDATE, "destroy": _DESTROY}

    def get_object(self) -> Any:
        raise AssertionError("a kernel write's target is its own selector's")


def _call(viewset: Any, method: str, action_name: str, body: Any = None, **kwargs: Any) -> Response:
    request = getattr(factory, method)("/", body, format="json")
    return viewset.as_view({method: action_name})(request, **kwargs)


@pytest.fixture
def author() -> Author:
    return Author.objects.create(name="a")


class TestTheTarget:
    @pytest.mark.parametrize(
        ("method", "action_name"), [("put", "update"), ("patch", "partial_update")]
    )
    def test_an_update_finds_its_row(self, author: Author, method: str, action_name: str) -> None:
        response = _call(_ViewSet, method, action_name, {"name": "b"}, pk=author.pk)
        assert response.data == {"id": author.pk, "name": "b"}

    def test_a_destroy_finds_its_row(self, author: Author) -> None:
        assert _call(_ViewSet, "delete", "destroy", pk=author.pk).status_code == 204
        assert not Author.objects.exists()

    def test_a_missing_row_is_404(self) -> None:
        assert _call(_ViewSet, "put", "update", {"name": "b"}, pk=999).status_code == 404

    def test_the_retrieve_entry_is_not_the_write_s_lookup(self, author: Author) -> None:
        other = Author.objects.create(name="other")

        class _WithRetrieve(_ViewSet):
            action_specs = {
                "update": _UPDATE,
                "retrieve": SelectorSpec(
                    kind=SelectorKind.RETRIEVE,
                    selector=lambda: other,
                    permissions=_OPEN,
                    presenter=SerializerPresenter(AuthorSerializer),
                ),
            }

        _call(_WithRetrieve, "put", "update", {"name": "b"}, pk=author.pk)
        assert Author.objects.get(pk=author.pk).name == "b"
        assert Author.objects.get(pk=other.pk).name == "other"

    def test_a_collection_target_takes_its_set(self) -> None:
        Author.objects.create(name="a")
        Author.objects.create(name="b")

        def rename_all(*, collection: QuerySet[Author], data: dict[str, Any]) -> None:
            collection.update(name=data["name"])

        spec = ServiceSpec(
            service=rename_all,
            permissions=_OPEN,
            validator=SerializerValidator(_NameIn),
            collection_selector_spec=SelectorSpec(
                kind=SelectorKind.LIST, selector=lambda: Author.objects.all()
            ),
        )

        class _Bulk(ServiceViewSet):
            action_specs = {"update": spec}

        assert _call(_Bulk, "put", "update", {"name": "z"}).status_code == 204
        assert set(Author.objects.values_list("name", flat=True)) == {"z"}


class TestObjectPermissions:
    def test_the_view_s_object_permission_refuses_the_row(self, author: Author) -> None:
        class _NoRows(BasePermission):
            def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
                return False

        class _Guarded(_ViewSet):
            permission_classes = [_NoRows]

        assert _call(_Guarded, "put", "update", {"name": "b"}, pk=author.pk).status_code == 403
        assert _call(_Guarded, "delete", "destroy", pk=author.pk).status_code == 403
        assert Author.objects.get().name == "a"
