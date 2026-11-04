"""A viewset method this package's handler refuses for want of a spec is left out of the schema.

A router binds every method of a ``ServiceViewSet``'s routes to a handler, and
the handler answers 405 where no spec serves its action, so ``Allow`` leaves
that method out on a route serving any spec. drf-spectacular reads the
router's action map, never ``Allow``, and documented each such method; the
schema now omits exactly what ``Allow`` omits. The list and retrieve handlers,
which fall back to DRF's own queryset, a handler the view defines itself, a
route serving no spec and a standalone view stay as they were.

Each viewset here is asked for its ``Allow`` too, so a test also fails where
the schema and the header part, not only where a method is missing.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.urls import path
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.routers import SimpleRouter
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceUpdateView, ServiceViewSet
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

_OPEN = (Unrestricted(),)
_BY_PK = Parameters.of(Parameter("pk", "integer", required=True))
_PRESENTER = SerializerPresenter(AuthorSerializer)


class _NameIn(serializers.Serializer):
    name = serializers.CharField(max_length=20)


def _list_authors() -> Any:
    return Author.objects.order_by("id")


def _get_author(*, pk: int) -> Author | None:
    return Author.objects.filter(pk=pk).first()


def _rename(*, instance: Author, data: Any) -> Any: ...


def _target() -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.RETRIEVE, selector=_get_author, reads=_BY_PK)


def _list() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST, selector=_list_authors, permissions=_OPEN, presenter=_PRESENTER
    )


def _retrieve() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=_get_author,
        reads=_BY_PK,
        permissions=_OPEN,
        presenter=_PRESENTER,
    )


def _update() -> ServiceSpec:
    return ServiceSpec(
        service=_rename,
        permissions=_OPEN,
        validator=SerializerValidator(_NameIn),
        presenter=_PRESENTER,
        instance_selector_spec=_target(),
    )


class _NoDestroy(ServiceViewSet):
    """Read and update specs, no create and no destroy, beside a handler of the view's own."""

    queryset = Author.objects.all()
    serializer_class = AuthorSerializer
    action_specs = {"list": _list(), "retrieve": _retrieve(), "update": _update()}

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["post"])
    def ping(self, request: Any, pk: str) -> Any: ...


class _PatchOnly(ServiceViewSet):
    """A ``partial_update`` spec alone: PUT reaches ``update``, which has none."""

    queryset = Author.objects.all()
    serializer_class = AuthorSerializer
    action_specs = {"partial_update": _update()}


_router = SimpleRouter()
_router.register("no-destroy", _NoDestroy, basename="no-destroy")
_router.register("patch-only", _PatchOnly, basename="patch-only")

urlpatterns = [
    *_router.urls,
    path(
        "standalone/<int:pk>/",
        type("_Standalone", (ServiceUpdateView,), {"spec": _update()}).as_view(),
    ),
]


@pytest.fixture(scope="module", autouse=True)
def _enable_openapi() -> None:
    enable_openapi()


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)


def _documented(schema: dict[str, Any], route: str) -> set[str]:
    return {method.upper() for method in schema["paths"][route]}


def _allow(viewset: type[ServiceViewSet], actions: dict[str, str], **kwargs: Any) -> set[str]:
    view = viewset.as_view(actions)
    response = view(APIRequestFactory().options("/"), **kwargs)
    return {method.strip() for method in response["Allow"].split(",")} - {"HEAD", "OPTIONS"}


_LIST = {"get": "list", "post": "create"}
_DETAIL = {
    "get": "retrieve",
    "put": "update",
    "patch": "partial_update",
    "delete": "destroy",
}


class TestARouteServingASpec:
    def test_a_destroy_with_no_spec_is_left_out_and_the_rest_stays(
        self, schema: dict[str, Any]
    ) -> None:
        assert _documented(schema, "/no-destroy/{id}/") == {"GET", "PUT", "PATCH"}

    def test_a_create_with_no_spec_is_left_out_beside_the_list(
        self, schema: dict[str, Any]
    ) -> None:
        assert _documented(schema, "/no-destroy/") == {"GET"}

    def test_a_handler_the_view_defines_itself_stays(self, schema: dict[str, Any]) -> None:
        assert _documented(schema, "/no-destroy/{id}/ping/") == {"POST"}

    def test_a_put_with_only_a_partial_update_spec_is_left_out(
        self, schema: dict[str, Any]
    ) -> None:
        # The retrieve handler falls back to DRF's queryset, so GET stays.
        assert _documented(schema, "/patch-only/{id}/") == {"GET", "PATCH"}

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("viewset", "actions", "route"),
        [
            (_NoDestroy, _LIST, "/no-destroy/"),
            (_NoDestroy, _DETAIL, "/no-destroy/{id}/"),
            (_PatchOnly, _DETAIL, "/patch-only/{id}/"),
        ],
    )
    def test_the_schema_documents_what_allow_names(
        self,
        schema: dict[str, Any],
        viewset: type[ServiceViewSet],
        actions: dict[str, str],
        route: str,
    ) -> None:
        assert _documented(schema, route) == _allow(viewset, actions)


class TestWhereNothingIsLeftOut:
    def test_a_route_serving_no_spec_is_documented_as_drf_routes_it(
        self, schema: dict[str, Any]
    ) -> None:
        # Neither list nor create has a spec, so the route answers as DRF does
        # and its Allow names POST: the schema keeps it.
        assert _documented(schema, "/patch-only/") == {"GET", "POST"}

    @pytest.mark.django_db
    def test_a_route_serving_no_spec_documents_what_allow_names(
        self, schema: dict[str, Any]
    ) -> None:
        assert _documented(schema, "/patch-only/") == _allow(_PatchOnly, _LIST)

    def test_a_standalone_view_is_documented_whole(self, schema: dict[str, Any]) -> None:
        assert _documented(schema, "/standalone/{id}/") == {"PUT", "PATCH"}
