"""``@selector_action`` serving a kernel ``SelectorSpec``.

The decorated action dispatches through the standalone selector views' own
edge (``dispatch_kernel_selector``), and the spec is asked at decoration what
``validate_selector_view_spec`` asks of a standalone view's, so each test fails
against a tree whose decorator reads drfs fields off the spec.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import (
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    Unrestricted,
)
from rest_framework.filters import BaseFilterBackend
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import GenericViewSet, ViewSet

from django_spec_rest import selector_action
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_PRESENTER = SerializerPresenter(AuthorSerializer)


class _DenyAll(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return False


class _NoRows(BasePermission):
    def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
        return False


class _Pages(PageNumberPagination):
    page_size = 2


class _DropsEverything(BaseFilterBackend):
    def filter_queryset(self, request: Any, queryset: Any, view: Any) -> Any:
        return queryset.none()


def _rows(**fields: Any) -> SelectorSpec:
    defaults: dict[str, Any] = {
        "selector": lambda: Author.objects.order_by("id"),
        "permissions": _OPEN,
        "presenter": _PRESENTER,
    }
    return SelectorSpec(kind=SelectorKind.LIST, **{**defaults, **fields})


def _row(**fields: Any) -> SelectorSpec:
    defaults: dict[str, Any] = {
        "selector": lambda *, pk: Author.objects.filter(pk=pk).first(),
        "reads": Parameters.of(Parameter("pk", "integer", required=True)),
        "permissions": _OPEN,
        "presenter": _PRESENTER,
    }
    return SelectorSpec(kind=SelectorKind.RETRIEVE, **{**defaults, **fields})


def _viewset(spec: SelectorSpec, *, base: type = GenericViewSet, **attrs: Any) -> Any:
    @selector_action(spec)
    def act(self: Any, request: Any, pk: Any = None) -> None:
        """Stubbed: the decorator serves the spec."""

    return type("_ViewSet", (base,), {"queryset": Author.objects.all(), "act": act, **attrs})


def _get(viewset: Any, **kwargs: Any) -> Response:
    return viewset.as_view({"get": "act"})(factory.get("/"), **kwargs)


@pytest.fixture
def authors() -> list[Author]:
    return [Author.objects.create(name=name) for name in "abc"]


class TestACollectionAction:
    @pytest.mark.parametrize("base", [GenericViewSet, ViewSet])
    def test_presents_its_rows_on_any_viewset(self, base: type, authors: list[Author]) -> None:
        response = _get(_viewset(_rows(), base=base))
        assert response.status_code == 200
        assert [row["name"] for row in response.data] == ["a", "b", "c"]

    def test_a_paginated_viewset_presents_the_page(self, authors: list[Author]) -> None:
        response = _get(_viewset(_rows(), pagination_class=_Pages))
        assert response.data["count"] == 3
        assert [row["name"] for row in response.data["results"]] == ["a", "b"]

    def test_no_filter_backend_applies(self, authors: list[Author]) -> None:
        response = _get(_viewset(_rows(), filter_backends=[_DropsEverything]))
        assert len(response.data) == 3

    def test_with_no_presenter_the_viewset_s_serializer_renders(
        self, authors: list[Author]
    ) -> None:
        response = _get(_viewset(_rows(presenter=None), serializer_class=AuthorSerializer))
        assert [row["name"] for row in response.data] == ["a", "b", "c"]

    def test_is_a_collection_route(self) -> None:
        assert _viewset(_rows()).act.detail is False


class TestADetailAction:
    def test_presents_its_row(self, authors: list[Author]) -> None:
        response = _get(_viewset(_row()), pk=authors[0].pk)
        assert response.status_code == 200
        assert response.data == {"id": authors[0].pk, "name": "a"}

    def test_a_miss_is_404(self) -> None:
        assert _get(_viewset(_row()), pk=999).status_code == 404

    def test_an_allow_none_miss_is_json_null(self) -> None:
        response = _get(_viewset(_row(allow_none=True)), pk=999)
        assert response.status_code == 200
        assert response.render().content == b"null"

    def test_with_no_presenter_the_viewset_s_serializer_renders(
        self, authors: list[Author]
    ) -> None:
        viewset = _viewset(_row(presenter=None), serializer_class=AuthorSerializer)
        assert _get(viewset, pk=authors[1].pk).data == {"id": authors[1].pk, "name": "b"}

    def test_the_view_s_object_permission_is_asked_of_the_row(self, authors: list[Author]) -> None:
        viewset = _viewset(_row(), permission_classes=[_NoRows])
        assert _get(viewset, pk=authors[0].pk).status_code == 403

    def test_is_a_detail_route(self) -> None:
        assert _viewset(_row()).act.detail is True


class TestPermissions:
    def test_the_spec_s_own_checks_refuse(self, authors: list[Author]) -> None:
        assert _get(_viewset(_rows(permissions=(_DenyAll(),)))).status_code == 403

    def test_no_permission_classes_are_forwarded_to_drf(self) -> None:
        assert "permission_classes" not in _viewset(_rows()).act.kwargs


class TestAtDecoration:
    def test_a_keyword_nothing_fills_is_refused(self) -> None:
        """The edge hands a kernel selector no view hook, so a keyword the
        spec's own declarations leave unfilled can be filled by nothing."""
        with pytest.raises(ImproperlyConfigured, match="owner"):
            _viewset(_rows(selector=lambda *, owner: None))

    def test_a_well_declared_spec_is_accepted(self) -> None:
        assert callable(_viewset(_rows()).as_view({"get": "act"}))


def test_methods_url_path_and_url_name_reach_the_route() -> None:
    """What the decorator forwards to DRF's ``@action`` is what the router
    routes: a ``POST`` read under its own path and name."""
    Author.objects.create(name="Ada")

    @selector_action(_rows(), methods=["post"], url_path="by-name", url_name="named")
    def recent(self: Any, request: Any) -> None:
        """Stubbed: the decorator serves the spec."""

    viewset = type("_ViewSet", (GenericViewSet,), {"recent": recent})
    router = SimpleRouter()
    router.register("authors", viewset, basename="authors")

    (route,) = [url for url in router.urls if url.name == "authors-named"]
    assert route.pattern.regex.pattern == "^authors/by-name/$"
    response = route.callback(factory.post("/"))
    assert response.status_code == 200
    assert [row["name"] for row in response.data] == ["Ada"]
