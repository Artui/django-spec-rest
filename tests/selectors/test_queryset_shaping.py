"""A kernel selector spec's queryset shaping, served by the query views.

``select_related``, ``prefetch_related``, ``annotations``, ``extend_queryset``
and ``filter_set`` are the kernel's own fields, applied by its dispatch in its
order; these tests hold that the views serve what they shape. The viewset,
``selector_action`` and output-selector sites are the viewsets' and the
mutation views' own.
"""

from __future__ import annotations

from typing import Any

import django_filters
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.db.models import Count, Prefetch, QuerySet
from django.test.utils import CaptureQueriesContext
from django_service_specs import Parameter, Parameters, SelectorKind, SelectorSpec, Unrestricted
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorListView, SelectorRetrieveView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Author, Post, Tag

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _PostWithAuthor(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.name", default=None)

    class Meta:
        model = Post
        fields = ("id", "title", "author_name")


class _PostWithTags(serializers.ModelSerializer):
    tag_names = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = ("id", "tag_names")

    def get_tag_names(self, post: Post) -> list[str]:
        return [tag.name for tag in post.tags.all()]


class _AuthorWithCount(serializers.Serializer):
    name = serializers.CharField()
    post_count = serializers.IntegerField()


def _posts() -> QuerySet[Post]:
    return Post.objects.order_by("id")


def _list(presenter: Any, selector: Any = _posts, **fields: Any) -> Any:
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=selector,
        permissions=_OPEN,
        presenter=SerializerPresenter(presenter),
        **fields,
    )
    return type("_View", (SelectorListView,), {"spec": spec}).as_view()


def _retrieve(presenter: Any, selector: Any, **fields: Any) -> Any:
    spec = SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=selector,
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
        permissions=_OPEN,
        presenter=SerializerPresenter(presenter),
        **fields,
    )
    return type("_View", (SelectorRetrieveView,), {"spec": spec}).as_view()


@pytest.fixture
def three_posts() -> list[Post]:
    return [
        Post.objects.create(title=f"p{i}", author=Author.objects.create(name=f"a{i}"))
        for i in range(3)
    ]


def _queries(view: Any, path: str = "/", **kwargs: Any) -> tuple[Any, int]:
    with CaptureQueriesContext(connection) as captured:
        response = view(factory.get(path), **kwargs)
    return response, len(captured)


class TestDeclarativeShaping:
    def test_select_related_serves_the_rows_in_one_query(self, three_posts: list[Post]) -> None:
        bare, n_bare = _queries(_list(_PostWithAuthor))
        shaped, n_shaped = _queries(_list(_PostWithAuthor, select_related=("author",)))
        assert shaped.data == bare.data
        assert [row["author_name"] for row in shaped.data] == ["a0", "a1", "a2"]
        assert n_shaped == 1 < n_bare

    def test_prefetch_related_by_name_and_by_object(self, three_posts: list[Post]) -> None:
        tag = Tag.objects.create(name="t")
        three_posts[0].tags.add(tag)
        for prefetch in ("tags", Prefetch("tags", queryset=Tag.objects.order_by("name"))):
            response, queries = _queries(_list(_PostWithTags, prefetch_related=(prefetch,)))
            assert [row["tag_names"] for row in response.data] == [["t"], [], []]
            assert queries == 2

    def test_an_annotation_is_on_every_row(self, three_posts: list[Post]) -> None:
        def authors() -> QuerySet[Author]:
            return Author.objects.order_by("id")

        view = _list(_AuthorWithCount, authors, annotations={"post_count": Count("posts")})
        assert [row["post_count"] for row in view(factory.get("/")).data] == [1, 1, 1]

    def test_select_related_applies_on_a_retrieve(self, three_posts: list[Post]) -> None:
        view = _retrieve(
            _PostWithAuthor,
            lambda *, pk: Post.objects.filter(pk=pk),
            select_related=("author",),
        )
        response, queries = _queries(view, pk=str(three_posts[1].pk))
        assert response.data["author_name"] == "a1"
        assert queries == 1


class TestExtendQueryset:
    def test_it_is_bound_by_name_and_runs_after_the_declarative_fields(
        self, three_posts: list[Post]
    ) -> None:
        seen: dict[str, Any] = {}

        def extend(*, queryset: QuerySet[Post], request: Any, view: Any) -> QuerySet[Post]:
            seen.update(related=queryset.query.select_related, request=request, view=view)
            return queryset.filter(title=request.query_params.get("only", "p1"))

        view = _list(
            _PostWithAuthor,
            select_related=("author",),
            extend_queryset=extend,
            reads=Parameters.of(Parameter("only", "string", required=False)),
        )
        response = view(factory.get("/?only=p2"))
        assert [row["title"] for row in response.data] == ["p2"]
        assert seen["related"] == {"author": {}}
        assert seen["view"].request is seen["request"]


class _ByTitle(django_filters.FilterSet):
    title = django_filters.CharFilter()
    views = django_filters.NumberFilter()

    class Meta:
        model = Post
        fields: list[str] = []


class TestFilterSet:
    def test_it_narrows_the_list_by_the_query_string(self, three_posts: list[Post]) -> None:
        response = _list(_PostWithAuthor, filter_set=_ByTitle)(factory.get("/?title=p1"))
        assert [row["title"] for row in response.data] == ["p1"]

    def test_it_is_applied_before_a_retrieve_takes_its_row(self, three_posts: list[Post]) -> None:
        """Every post matches the selector; the filter decides which is first."""
        view = _retrieve(
            _PostWithAuthor, lambda *, pk: Post.objects.order_by("id"), filter_set=_ByTitle
        )
        response = view(factory.get("/?title=p2"), pk="0")
        assert response.data["title"] == "p2"

    def test_it_composes_with_select_related(self, three_posts: list[Post]) -> None:
        view = _list(_PostWithAuthor, filter_set=_ByTitle, select_related=("author",))
        response, queries = _queries(view, "/?title=p0")
        assert [row["author_name"] for row in response.data] == ["a0"]
        assert queries == 1

    def test_a_request_scoped_filter_set_is_handed_the_request(
        self, three_posts: list[Post]
    ) -> None:
        seen: list[Any] = []

        class _Scoped(_ByTitle):
            def __init__(self, *args: Any, request: Any = None, **kwargs: Any) -> None:
                seen.append(request)
                super().__init__(*args, request=request, **kwargs)

        _list(_PostWithAuthor, filter_set=_Scoped)(factory.get("/?title=p0"))
        assert seen and seen[0] is not None
        assert seen[0].query_params["title"] == "p0"

    def test_an_invalid_filter_value_is_a_400_under_the_filter_s_name(
        self, three_posts: list[Post]
    ) -> None:
        response = _list(_PostWithAuthor, filter_set=_ByTitle)(factory.get("/?views=many"))
        assert response.status_code == 400
        assert list(response.data) == ["views"]


class TestShapingANonQueryset:
    def test_shaping_a_list_the_selector_returned_fails_loud(self) -> None:
        view = _list(_PostWithAuthor, lambda: [], select_related=("author",))
        with pytest.raises(ImproperlyConfigured, match="QuerySet"):
            view(factory.get("/"))

    def test_a_filter_set_alone_on_a_list_fails_loud_too(self) -> None:
        view = _list(_PostWithAuthor, lambda: [], filter_set=_ByTitle)
        with pytest.raises(ImproperlyConfigured, match="QuerySet"):
            view(factory.get("/"))
