"""A spec's rows come from its selector alone, and filter backends narrow only a ``list``.

States the "Views and viewsets" page of the move-from-drfs guide over a real
viewset: no action a spec serves (``list``, ``retrieve``, a
``@selector_action``, a write's target) takes its rows from the view's
``get_queryset()``, and the view's ``filter_backends`` narrow a spec's ``list``
and nothing else. The viewset here overrides ``get_queryset()`` to a set that
would answer nothing and records every ask; its one filter backend hides the
author ``"b"``, a row each other action reaches all the same.

A permission class that asks ``get_queryset()`` (DRF's ``DjangoModelPermissions``)
is not asked about: none is declared here, so a recorded ask is the action's own.
"""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.filters import BaseFilterBackend
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceViewSet, selector_action
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_PRESENTER = SerializerPresenter(AuthorSerializer)
_BY_PK = Parameters.of(Parameter("pk", "integer", required=True))

_ASKED: list[str] = []


class _NameIn(serializers.Serializer):
    name = serializers.CharField()


class _HidesB(BaseFilterBackend):
    def filter_queryset(self, request: Any, queryset: Any, view: Any) -> Any:
        return queryset.exclude(name="b")


def _all() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda: Author.objects.order_by("id"),
        permissions=_OPEN,
        presenter=_PRESENTER,
    )


def _one(**fields: Any) -> SelectorSpec:
    defaults: dict[str, Any] = {
        "selector": lambda *, pk: Author.objects.filter(pk=pk).first(),
        "reads": _BY_PK,
        "permissions": _OPEN,
        "presenter": _PRESENTER,
    }
    return SelectorSpec(kind=SelectorKind.RETRIEVE, **{**defaults, **fields})


def _target() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
        reads=_BY_PK,
    )


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
    presenter=_PRESENTER,
    instance_selector_spec=_target(),
)
_DESTROY = ServiceSpec(service=_delete, permissions=_OPEN, instance_selector_spec=_target())


class _ViewSet(ServiceViewSet):
    queryset = Author.objects.all()
    filter_backends = [_HidesB]
    action_specs = {"list": _all(), "retrieve": _one()}

    def get_queryset(self) -> Any:
        _ASKED.append(str(self.action))
        return Author.objects.none()

    @selector_action(_all())
    def every(self, request: Any) -> None:
        """Stubbed: the decorator serves the spec."""

    @selector_action(_one())
    def one(self, request: Any, pk: Any = None) -> None:
        """Stubbed: the decorator serves the spec."""


class _WriteViewSet(_ViewSet):
    """No ``"retrieve"`` entry, so ``get_object()`` is DRF's own, as a project's was in drfs.

    ``SelectorRetrieveMixin`` replaces ``get_object()`` with the retrieve spec's
    lookup when one is wired, which would find the row for a write whatever the
    write did: with none wired, a write that fell back to ``get_object()`` would
    ask ``get_queryset()`` and the filter backends, and these tests would see it.
    """

    action_specs = {"update": _UPDATE, "destroy": _DESTROY}


def _call(
    method: str, action_name: str, body: Any = None, *, viewset: Any = _ViewSet, **kwargs: Any
) -> Response:
    request = getattr(factory, method)("/", body, format="json")
    return viewset.as_view({method: action_name})(request, **kwargs)


@pytest.fixture(autouse=True)
def _no_asks() -> None:
    _ASKED.clear()


@pytest.fixture
def authors() -> dict[str, Author]:
    return {name: Author.objects.create(name=name) for name in "abc"}


class TestListIsNarrowedByTheFilterBackends:
    def test_a_filter_backend_narrows_the_list(self, authors: dict[str, Author]) -> None:
        response = _call("get", "list")
        assert [row["name"] for row in response.data] == ["a", "c"]

    def test_get_queryset_does_not_supply_the_list_rows(self, authors: dict[str, Author]) -> None:
        _call("get", "list")
        assert _ASKED == []


class TestNoOtherActionIsNarrowedOrFedByTheView:
    def test_retrieve_reaches_the_row_the_backend_hides(self, authors: dict[str, Author]) -> None:
        response = _call("get", "retrieve", pk=authors["b"].pk)
        assert response.status_code == 200
        assert response.data == {"id": authors["b"].pk, "name": "b"}
        assert _ASKED == []

    def test_a_collection_selector_action_is_not_narrowed(self, authors: dict[str, Author]) -> None:
        response = _call("get", "every")
        assert [row["name"] for row in response.data] == ["a", "b", "c"]
        assert _ASKED == []

    def test_a_detail_selector_action_reaches_the_row_the_backend_hides(
        self, authors: dict[str, Author]
    ) -> None:
        response = _call("get", "one", pk=authors["b"].pk)
        assert response.status_code == 200
        assert response.data == {"id": authors["b"].pk, "name": "b"}
        assert _ASKED == []

    def test_an_update_reaches_the_row_the_backend_hides(self, authors: dict[str, Author]) -> None:
        response = _call("put", "update", {"name": "z"}, viewset=_WriteViewSet, pk=authors["b"].pk)
        assert response.status_code == 200
        assert Author.objects.get(pk=authors["b"].pk).name == "z"
        assert _ASKED == []

    def test_a_destroy_reaches_the_row_the_backend_hides(self, authors: dict[str, Author]) -> None:
        response = _call("delete", "destroy", viewset=_WriteViewSet, pk=authors["b"].pk)
        assert response.status_code == 204
        assert not Author.objects.filter(pk=authors["b"].pk).exists()
        assert _ASKED == []
