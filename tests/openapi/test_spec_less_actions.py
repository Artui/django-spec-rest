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
from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.routers import SimpleRouter
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorViewSet, ServiceUpdateView, ServiceViewSet
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


class _OwnDestroy(ServiceViewSet):
    """Read specs beside a ``destroy`` the viewset defines itself, unmarked and so its own."""

    queryset = Author.objects.all()
    serializer_class = AuthorSerializer
    action_specs = {"list": _list(), "retrieve": _retrieve()}

    def destroy(self, request: Any, *args: Any, **kwargs: Any) -> Any: ...


class _PatchOnly(ServiceViewSet):
    """A ``partial_update`` spec alone: PUT reaches ``update``, which has none."""

    queryset = Author.objects.all()
    serializer_class = AuthorSerializer
    action_specs = {"partial_update": _update()}


_router = SimpleRouter()
_router.register("no-destroy", _NoDestroy, basename="no-destroy")
_router.register("patch-only", _PatchOnly, basename="patch-only")
_router.register("own-destroy", _OwnDestroy, basename="own-destroy")

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
        # The route serves the retrieve spec, so PUT and PATCH, with no update spec, are left out.
        assert _documented(schema, "/own-destroy/{id}/") == {"GET", "DELETE"}

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
            (_OwnDestroy, _DETAIL, "/own-destroy/{id}/"),
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


@extend_schema_view(
    update=extend_schema(exclude=True),
    destroy=extend_schema(summary="Delete an author"),
)
class _UpdateExcluded(_NoDestroy):
    """``_NoDestroy`` with PUT left out by the decorator, DELETE by the missing spec."""


class TestAnExcludeComposesWithTheSpecLessRule:
    """``extend_schema`` wraps a view's schema class, and the wrapper still asks ours.

    The wrapper's ``is_excluded`` returns its ``exclude`` for a decorated
    action and otherwise calls ``super()``. ``destroy`` is decorated without
    excluding anything, so its DELETE is answered through that ``super()`` call
    and only ``ServiceAutoSchema``'s spec-less rule leaves it out: the test
    fails if the wrapper stops asking, or if our rule stops answering. It does
    not fail if ``ServiceAutoSchema`` stops calling its own ``super()``, which
    answers False for this view anyway. Unlike the viewsets above, this one's
    schema and ``Allow`` differ on purpose: ``Allow`` still names PUT.
    """

    def test_update_excluded_by_the_decorator_leaves_get_and_patch(self) -> None:
        router = SimpleRouter()
        router.register("x", _UpdateExcluded, basename="x")

        schema = SchemaGenerator(patterns=router.urls).get_schema(request=None, public=True)

        assert _documented(schema, "/x/{id}/") == {"GET", "PATCH"}


class TestWhereNothingIsLeftOut:
    def test_a_route_serving_no_spec_is_documented_as_drf_routes_it(
        self, schema: dict[str, Any]
    ) -> None:
        # Neither list nor create has a spec.
        assert _documented(schema, "/patch-only/") == {"GET", "POST"}

    @pytest.mark.django_db
    def test_a_route_serving_no_spec_documents_what_allow_names(
        self, schema: dict[str, Any]
    ) -> None:
        assert _documented(schema, "/patch-only/") == _allow(_PatchOnly, _LIST)

    def test_an_extra_action_s_own_route_is_documented(self, schema: dict[str, Any]) -> None:
        # ``@action`` routes ``ping`` alone, a route serving no spec.
        assert _documented(schema, "/no-destroy/{id}/ping/") == {"POST"}

    def test_a_standalone_view_is_documented_whole(self, schema: dict[str, Any]) -> None:
        assert _documented(schema, "/standalone/{id}/") == {"PUT", "PATCH"}


def _make() -> Any: ...


_CREATE = ServiceSpec(service=_make, permissions=_OPEN, presenter=_PRESENTER)


class _CreateOnly(ServiceViewSet):
    action_specs = {"create": _CREATE}


class _RowsNoSerializer(ServiceViewSet):
    action_specs = {"create": _CREATE}
    queryset = Author.objects.all()


class _ListSpecAlone(ServiceViewSet):
    action_specs = {"list": _list()}


class _SelectorRetrieveAlone(SelectorViewSet):
    action_specs = {"retrieve": _retrieve()}


class _SelectorListAlone(SelectorViewSet):
    action_specs = {"list": _list()}


class _CreateBesideAFallback(ServiceViewSet):
    """A create spec beside a ``queryset`` and a ``serializer_class``: the reads can fall back."""

    action_specs = {"create": _CREATE}
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer


class _OwnGetQueryset(ServiceViewSet):
    action_specs = {"create": _CREATE}
    serializer_class = AuthorSerializer

    def get_queryset(self) -> Any: ...


class _OwnGetObject(ServiceViewSet):
    action_specs = {"create": _CREATE}
    serializer_class = AuthorSerializer

    def get_object(self) -> Any: ...


class TestAViewSetWhoseFallbackCannotRun:
    """A read with nothing to fall back to answers 405, so it is no operation either."""

    @pytest.fixture
    def errors(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """What drf-spectacular reports as ``Error [...]``, which it prints and then caches."""
        emitted: list[str] = []

        def emit(message: str, severity: str) -> None:
            if severity == "error":
                emitted.append(message)

        monkeypatch.setattr(GENERATOR_STATS, "emit", emit)
        return emitted

    @staticmethod
    def _schema(viewset: type) -> dict[str, Any]:
        router = SimpleRouter()
        router.register("x", viewset, basename="x")
        return SchemaGenerator(patterns=router.urls).get_schema(request=None, public=True)

    @pytest.mark.parametrize("viewset", [_CreateOnly, _RowsNoSerializer])
    def test_a_create_spec_alone_documents_post_alone(self, viewset: type) -> None:
        schema = self._schema(viewset)
        assert _documented(schema, "/x/") == {"POST"}
        assert "/x/{id}/" not in schema["paths"]

    def test_generation_reports_no_error(self, errors: list[str]) -> None:
        self._schema(_CreateOnly)
        assert errors == []

    def test_a_list_spec_alone_documents_no_detail_route(self) -> None:
        schema = self._schema(_ListSpecAlone)
        assert _documented(schema, "/x/") == {"GET"}
        assert "/x/{id}/" not in schema["paths"]

    def test_a_selector_retrieve_alone_documents_no_list_route(self) -> None:
        schema = self._schema(_SelectorRetrieveAlone)
        assert _documented(schema, "/x/{id}/") == {"GET"}
        assert "/x/" not in schema["paths"]

    def test_a_selector_list_alone_documents_no_detail_route(self) -> None:
        schema = self._schema(_SelectorListAlone)
        assert _documented(schema, "/x/") == {"GET"}
        assert "/x/{id}/" not in schema["paths"]

    def test_an_own_get_object_keeps_its_read_documented(self) -> None:
        schema = self._schema(_OwnGetObject)
        assert _documented(schema, "/x/") == {"POST"}
        assert _documented(schema, "/x/{id}/") == {"GET"}

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        ("viewset", "actions", "route"),
        [
            (_CreateOnly, _LIST, "/x/"),
            (_RowsNoSerializer, _LIST, "/x/"),
            (_ListSpecAlone, _LIST, "/x/"),
            (_SelectorListAlone, {"get": "list"}, "/x/"),
            (_SelectorRetrieveAlone, {"get": "retrieve"}, "/x/{id}/"),
            (_OwnGetObject, _LIST, "/x/"),
            (_OwnGetObject, _DETAIL, "/x/{id}/"),
        ],
    )
    def test_the_schema_documents_what_allow_names(
        self, viewset: type, actions: dict[str, str], route: str
    ) -> None:
        assert _documented(self._schema(viewset), route) == _allow(viewset, actions)


class TestAFallbackThatCanRunStaysDocumented:
    @pytest.mark.parametrize("viewset", [_CreateBesideAFallback, _OwnGetQueryset])
    def test_the_reads_stay_beside_the_create(self, viewset: type) -> None:
        router = SimpleRouter()
        router.register("x", viewset, basename="x")
        schema = SchemaGenerator(patterns=router.urls).get_schema(request=None, public=True)
        assert _documented(schema, "/x/") == {"GET", "POST"}
        assert _documented(schema, "/x/{id}/") == {"GET", "PUT", "PATCH", "DELETE"}
