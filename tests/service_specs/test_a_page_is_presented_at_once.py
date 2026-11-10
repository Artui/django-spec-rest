from __future__ import annotations

import json
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.db.models import Q, QuerySet
from django.test.utils import CaptureQueriesContext
from django_service_specs import (
    Affordance,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
    dispatch,
    present,
)
from django_service_specs.output.presentation_context import PresentationContext
from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorListView, SelectorRetrieveView, ServiceCreateView
from django_spec_rest.service_specs.drf_invalid_arguments import DRFInvalidArguments
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Post

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


def _body(response: Any) -> Any:
    response.render()
    return json.loads(response.content)


class _Counted(serializers.ModelSerializer):
    """A row rendering what the page's one lookup left in the context."""

    seen = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = ("id", "seen")

    def get_seen(self, post: Post) -> int:
        return self.context["seen"][post.pk]


def _posts(count: int) -> list[Post]:
    return [Post.objects.create(title=f"p{n}") for n in range(count)]


def _paged(size: int, provider: Any) -> Any:
    class _Page(PageNumberPagination):
        page_size = size

    return type(
        "_View",
        (SelectorListView,),
        {
            "pagination_class": _Page,
            "spec": SelectorSpec(
                kind=SelectorKind.LIST,
                selector=lambda: Post.objects.order_by("id"),
                permissions=_OPEN,
                presenter=SerializerPresenter(_Counted, serializer_context=provider),
            ),
        },
    )


class TestThePageIsAskedForOnce:
    def test_a_callable_declaring_the_page_is_asked_once_per_page(self) -> None:
        posts = _posts(5)
        asked: list[tuple[int, ...]] = []

        def batched(*, request: Any, page: Any) -> dict[str, Any]:
            asked.append(tuple(post.pk for post in page))
            ids = [post.pk for post in page]
            return {
                "seen": {
                    pk: n
                    for n, pk in enumerate(
                        Post.objects.filter(pk__in=ids).order_by("id").values_list("pk", flat=True)
                    )
                }
            }

        body = _body(_paged(3, batched).as_view()(factory.get("/")))

        assert asked == [tuple(post.pk for post in posts[:3])]
        assert [row["seen"] for row in body["results"]] == [0, 1, 2]

    def test_the_queries_a_page_costs_do_not_grow_with_its_rows(self) -> None:
        _posts(6)

        # Declares no value, so the count alone shows whether it is asked once per page or per row.
        def one_query() -> dict[str, Any]:
            return {"seen": dict.fromkeys(Post.objects.values_list("pk", flat=True), 1)}

        def cost(size: int) -> int:
            with CaptureQueriesContext(connection) as queries:
                _paged(size, one_query).as_view()(factory.get("/"))
            return len(queries)

        assert cost(2) == cost(5)

    def test_the_page_is_offered_under_the_value_keyword_too(self) -> None:
        _posts(2)
        received: list[dict[str, Any]] = []

        def provider(**pool: Any) -> dict[str, Any]:
            received.append(pool)
            return {"seen": {post.pk: 0 for post in pool["page"]}}

        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=lambda: Post.objects.order_by("id"),
            permissions=_OPEN,
            presenter=SerializerPresenter(
                _Counted, serializer_context=provider, value_keyword="rows"
            ),
        )

        present(spec, dispatch(spec, principal=AnonymousUser(), arguments={}))

        assert len(received) == 1
        assert received[0]["rows"] is received[0]["page"]
        assert [post.title for post in received[0]["page"]] == ["p0", "p1"]

    def test_a_presenter_naming_no_value_keyword_offers_the_page_alone(self) -> None:
        _posts(2)
        received: list[dict[str, Any]] = []

        def provider(**pool: Any) -> dict[str, Any]:
            received.append(pool)
            return {"seen": {post.pk: 0 for post in pool["page"]}}

        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=lambda: Post.objects.order_by("id"),
            permissions=_OPEN,
            presenter=SerializerPresenter(
                _Counted, serializer_context=provider, value_keyword=None
            ),
        )

        present(spec, dispatch(spec, principal=AnonymousUser(), arguments={}))

        assert len(received) == 1
        assert not {"result", "instance"} & set(received[0])

    def test_a_many_service_s_callable_and_view_hook_are_handed_its_whole_return(self) -> None:
        asked: list[Any] = []

        class _Row(serializers.Serializer):
            title = serializers.CharField()
            hook = serializers.SerializerMethodField()
            spec = serializers.SerializerMethodField()

            def get_hook(self, _: Any) -> int:
                return self.context["hook"]

            def get_spec(self, _: Any) -> int:
                return self.context["spec"]

        def provider(*, result: Any) -> dict[str, Any]:
            asked.append(result)
            return {"spec": len(result)}

        class _View(ServiceCreateView):
            spec = ServiceSpec(
                service=lambda: [{"title": "a"}, {"title": "b"}],
                permissions=_OPEN,
                returns_many=True,
                presenter=SerializerPresenter(_Row, serializer_context=provider),
            )

            def get_output_serializer_context(self, *, result: Any) -> dict[str, Any]:
                return {"hook": len(result)}

        body = _body(_View.as_view()(factory.post("/", {}, format="json")))

        assert body == [
            {"title": "a", "hook": 2, "spec": 2},
            {"title": "b", "hook": 2, "spec": 2},
        ]
        assert len(asked) == 1


class _Tagged(serializers.ListSerializer):
    def to_representation(self, data: Any) -> list[Any]:
        return [{**row, "position": n} for n, row in enumerate(super().to_representation(data))]


class _TitledInList(serializers.ModelSerializer):
    class Meta:
        model = Post
        fields = ("id", "title")
        list_serializer_class = _Tagged


class TestTheRowsRenderAsOneManyRender:
    def test_a_list_serializer_class_renders_a_page(self) -> None:
        _posts(2)
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=lambda: Post.objects.order_by("id"),
            permissions=_OPEN,
            presenter=SerializerPresenter(_TitledInList),
        )
        view = type("_View", (SelectorListView,), {"spec": spec})

        body = _body(view.as_view()(factory.get("/")))

        assert [(row["title"], row["position"]) for row in body] == [("p0", 0), ("p1", 1)]

    def test_one_value_presents_through_presented_with_its_own_context(self) -> None:
        (post,) = _posts(1)
        received: list[Any] = []

        def provider(*, instance: Any) -> dict[str, Any]:
            received.append(instance)
            return {}

        spec = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, pk: Post.objects.filter(pk=pk).first(),
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
            permissions=_OPEN,
            presenter=SerializerPresenter(
                _TitledInList, serializer_context=provider, value_keyword="instance"
            ),
        )
        view = type("_View", (SelectorRetrieveView,), {"spec": spec})

        body = _body(view.as_view()(factory.get("/"), pk=str(post.pk)))

        # The list serializer is a set's: one value renders without it.
        assert body == {"id": post.pk, "title": "p0"}
        assert received == [post]

    def test_a_page_with_no_call_renders_under_the_description_context(self) -> None:
        posts = _posts(2)
        asked: list[None] = []
        presenter = SerializerPresenter(
            _TitledInList, serializer_context=lambda: asked.append(None) or {}
        )

        rows = presenter.presented_rows(tuple(posts), None)

        assert [row["position"] for row in rows] == [0, 1]
        assert asked == []

    def test_a_refusal_on_a_page_leaves_as_the_kernel_s(self) -> None:
        class _Refusing(serializers.Serializer):
            title = serializers.CharField()

            def to_representation(self, instance: Any) -> Any:
                raise serializers.ValidationError(["Nope."], code="nope")

        presenter = SerializerPresenter(_Refusing)
        context = PresentationContext(principal=None)

        with pytest.raises(DRFInvalidArguments) as refused:
            presenter.presented_rows(({"title": "a"},), context)

        assert refused.value.detail == {NON_FIELD_ERRORS: ["Nope."]}
        assert refused.value.get_codes() == {NON_FIELD_ERRORS: ["nope"]}  # ty: ignore[unresolved-attribute]


class TestAPageOfRowsAndNones:
    def test_a_none_row_is_presented_as_none_in_its_place(self) -> None:
        posts = _posts(2)
        presenter = SerializerPresenter(_TitledInList)

        rows = presenter.presented_rows((posts[0], None, posts[1]), PresentationContext(None))

        assert rows == [
            {"id": posts[0].pk, "title": "p0", "position": 0},
            None,
            {"id": posts[1].pk, "title": "p1", "position": 1},
        ]

    def test_a_list_serializer_answering_another_count_beside_a_none_is_refused(self) -> None:
        class _Dropping(serializers.ListSerializer):
            def to_representation(self, data: Any) -> list[Any]:
                return super().to_representation(data)[1:]

        class _Out(serializers.ModelSerializer):
            class Meta:
                model = Post
                fields = ("id",)
                list_serializer_class = _Dropping

        posts = _posts(2)

        with pytest.raises(ImproperlyConfigured, match="2 rows"):
            SerializerPresenter(_Out).presented_rows(
                (posts[0], None, posts[1]), PresentationContext(None)
            )


class TestAPageWithNoNone:
    def test_a_list_serializer_answering_another_count_is_refused_by_the_kernel(self) -> None:
        class _Dropping(serializers.ListSerializer):
            def to_representation(self, data: Any) -> list[Any]:
                return super().to_representation(data)[1:]

        class _Out(serializers.ModelSerializer):
            class Meta:
                model = Post
                fields = ("id",)
                list_serializer_class = _Dropping

        _posts(2)
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=lambda: Post.objects.order_by("id"),
            permissions=_OPEN,
            presenter=SerializerPresenter(_Out),
        )
        view = type("_View", (SelectorListView,), {"spec": spec})

        # With no ``None`` on the page the presenter hands the render back as it is.
        with pytest.raises(
            ImproperlyConfigured,
            match=r"^SerializerPresenter\.presented_rows answered with a list of 1 for 2 rows\.",
        ):
            view.as_view()(factory.get("/"))


UNPUBLISHED = Affordance(
    code="already_published", reason="This post is already published.", when=Q(published=False)
)


def _ordered() -> QuerySet[Post]:
    return Post.objects.order_by("id")


def test_each_row_of_a_page_keeps_its_own_affordances_in_order() -> None:
    Post.objects.create(title="draft")
    Post.objects.create(title="out", published=True)
    Post.objects.create(title="draft too")
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=_ordered,
        permissions=_OPEN,
        presenter=SerializerPresenter(_TitledInList),
        affordances={
            "publish": ServiceSpec(
                service=lambda: None, permissions=_OPEN, affordances=[UNPUBLISHED]
            )
        },
    )
    view = type("_View", (SelectorListView,), {"spec": spec})

    body = _body(view.as_view()(factory.get("/")))

    assert [
        (row["title"], row["position"], row["affordances"]["publish"]["available"]) for row in body
    ] == [("draft", 0, True), ("out", 1, False), ("draft too", 2, True)]
