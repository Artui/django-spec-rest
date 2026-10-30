"""``SelectorViewSet`` serving kernel ``SelectorSpec`` entries.

``list`` and ``retrieve`` dispatch through the selector views' own edge
(``dispatch_kernel_selector``), and are presented by the spec, as
``SelectorListView`` and ``SelectorRetrieveView`` present a kernel spec.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q, QuerySet
from django_service_specs import (
    Affordance,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.filters import BaseFilterBackend
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import SelectorViewSet, ServiceCreateMixin
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Post

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _PostOut(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()


class _DraftsOnly(BaseFilterBackend):
    def filter_queryset(self, request: Any, queryset: Any, view: Any) -> Any:
        return queryset.filter(published=False)


UNPUBLISHED = Affordance(
    code="already_published", reason="This post is already published.", when=Q(published=False)
)
PUBLISH = ServiceSpec(service=lambda: None, permissions=_OPEN, affordances=[UNPUBLISHED])


def _posts() -> QuerySet[Post]:
    return Post.objects.order_by("id")


def _list(**fields: Any) -> SelectorSpec:
    defaults: dict[str, Any] = {
        "selector": _posts,
        "permissions": _OPEN,
        "presenter": SerializerPresenter(_PostOut),
    }
    return SelectorSpec(kind=SelectorKind.LIST, **{**defaults, **fields})


def _retrieve(**fields: Any) -> SelectorSpec:
    defaults: dict[str, Any] = {
        "selector": lambda *, pk: Post.objects.filter(pk=pk).first(),
        "reads": Parameters.of(Parameter("pk", "integer", required=True)),
        "permissions": _OPEN,
        "presenter": SerializerPresenter(_PostOut),
    }
    return SelectorSpec(kind=SelectorKind.RETRIEVE, **{**defaults, **fields})


def _viewset(base: type = SelectorViewSet, **attrs: Any) -> Any:
    return type("_ViewSet", (base,), {"queryset": Post.objects.all(), **attrs})


def _get(viewset: Any, action_name: str, **kwargs: Any) -> Response:
    return viewset.as_view({"get": action_name})(factory.get("/"), **kwargs)


@pytest.fixture
def posts() -> tuple[Post, Post]:
    return (
        Post.objects.create(title="draft", published=False),
        Post.objects.create(title="out", published=True),
    )


class TestTheActions:
    def test_list_is_presented_by_the_spec(self, posts: tuple[Post, Post]) -> None:
        response = _get(_viewset(action_specs={"list": _list()}), "list")
        assert [row["title"] for row in response.data] == ["draft", "out"]

    def test_list_applies_the_view_s_filter_backends(self, posts: tuple[Post, Post]) -> None:
        viewset = _viewset(action_specs={"list": _list()}, filter_backends=[_DraftsOnly])
        assert [row["title"] for row in _get(viewset, "list").data] == ["draft"]

    def test_retrieve_is_presented_by_the_spec(self, posts: tuple[Post, Post]) -> None:
        response = _get(
            _viewset(action_specs={"retrieve": _retrieve()}), "retrieve", pk=posts[1].pk
        )
        assert response.data == {"id": posts[1].pk, "title": "out"}

    def test_retrieve_of_no_row_is_404(self) -> None:
        viewset = _viewset(action_specs={"retrieve": _retrieve()})
        assert _get(viewset, "retrieve", pk=999).status_code == 404

    def test_get_queryset_answers_the_list_spec_s_set(self, posts: tuple[Post, Post]) -> None:
        """A handler of the view's own reading ``get_queryset()`` reads the
        spec's set, as on the drfs path."""

        class _ViewSet(SelectorViewSet):
            queryset = Post.objects.none()
            action_specs = {"list": _list(selector=lambda: Post.objects.filter(published=True))}

            @action(detail=False)
            def titles(self, request: Any) -> Response:
                return Response([post.title for post in self.get_queryset()])

        assert _get(_ViewSet, "titles").data == ["out"]


class TestAffordances:
    def test_each_listed_row_carries_its_answers(self, posts: tuple[Post, Post]) -> None:
        viewset = _viewset(action_specs={"list": _list(affordances={"publish": PUBLISH})})
        rows = _get(viewset, "list").data
        assert [row["affordances"]["publish"]["available"] for row in rows] == [True, False]

    def test_affordances_with_no_presenter_are_refused_rather_than_dropped(
        self, posts: tuple[Post, Post]
    ) -> None:
        spec = _list(presenter=None, affordances={"publish": PUBLISH})
        viewset = _viewset(action_specs={"list": spec}, serializer_class=_PostOut)
        with pytest.raises(ImproperlyConfigured, match="Declare a presenter"):
            _get(viewset, "list")


class TestAsView:
    @pytest.mark.parametrize("action_name", ["list", "retrieve"])
    def test_the_default_selector_hook_is_not_an_override(self, action_name: str) -> None:
        entry = _list() if action_name == "list" else _retrieve()
        assert callable(_viewset(action_specs={action_name: entry}).as_view({"get": action_name}))

    def test_a_selector_hook_on_a_viewset_with_no_selector_mixin_is_refused(self) -> None:
        """No selector mixin, no default: a ``get_selector_kwargs`` there is the
        viewset's own, and never reaches a kernel spec."""
        viewset = _viewset(
            base=type("_Base", (ServiceCreateMixin, GenericViewSet), {}),
            action_specs={"list": _list()},
            get_selector_kwargs=lambda self: {},
        )
        with pytest.raises(ImproperlyConfigured, match="get_selector_kwargs"):
            viewset.as_view({"post": "create"})

    def test_a_viewset_with_no_selector_mixin_and_no_hook_passes(self) -> None:
        viewset = _viewset(
            base=type("_Base", (ServiceCreateMixin, GenericViewSet), {}),
            action_specs={"list": _list()},
        )
        assert callable(viewset.as_view({"post": "create"}))
