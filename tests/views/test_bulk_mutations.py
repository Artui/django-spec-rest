"""Bulk mutations through the HTTP views over kernel specs: ``many`` bodies and collection targets.

Changed by design: a drfs collection spec read its filters from the query
string beside the body; a kernel service spec's arguments are its body and the
route captures it declares, so a collection selector's reads come from those
and the query string is no argument of a write.
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
    ServiceError,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.test import APIRequestFactory

from django_spec_rest import (
    ServiceCreateView,
    ServiceDeleteView,
    ServiceUpdateView,
    delete_collection,
)
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author, Post

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _PostIn(serializers.Serializer):
    title = serializers.CharField()


class _PostSerializer(serializers.ModelSerializer):
    class Meta:
        model = Post
        fields = ("id", "title")


def _bulk_create(*, data: list[dict[str, Any]]) -> list[Post]:
    return [Post.objects.create(title=row["title"]) for row in data]


def _all_posts() -> QuerySet[Post]:
    return Post.objects.all().order_by("id")


_MANY = ServiceSpec(
    service=_bulk_create,
    permissions=_OPEN,
    validator=SerializerValidator(_PostIn),
    presenter=SerializerPresenter(_PostSerializer),
    many=True,
    atomic=False,
)


def _view(base: type, spec: ServiceSpec, **attrs: Any) -> Any:
    return type("_View", (base,), {"spec": spec, **attrs}).as_view()


def _collection(selector: Any = _all_posts, **seats: Any) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.LIST, selector=selector, **seats)


class TestBulkCreateMany:
    def test_list_in_list_out_201(self) -> None:
        response = _view(ServiceCreateView, _MANY)(
            factory.post("/", [{"title": "a"}, {"title": "b"}], format="json")
        )
        assert response.status_code == 201
        assert [row["title"] for row in response.data] == ["a", "b"]

    def test_a_list_body_is_never_looked_up(self) -> None:
        """A ``many`` call resolves no target, so the view's object permissions
        are asked of nothing, and the rows are created."""

        class _DenyObject(BasePermission):
            def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
                return False

        view = _view(ServiceCreateView, _MANY, permission_classes=[_DenyObject])
        assert view(factory.post("/", [{"title": "a"}], format="json")).status_code == 201

    def test_callable_success_status_on_a_bulk_body(self) -> None:
        view = _view(
            ServiceCreateView, _MANY, success_status=lambda *, result: 200 if result else 201
        )
        assert view(factory.post("/", [{"title": "a"}], format="json")).status_code == 200

    def test_callable_success_status_on_an_empty_body(self) -> None:
        spec = ServiceSpec(
            service=lambda *, data: None,
            permissions=_OPEN,
            validator=SerializerValidator(_PostIn),
            many=True,
        )
        view = _view(ServiceCreateView, spec, success_status=lambda: 202)
        response = view(factory.post("/", [{"title": "a"}], format="json"))
        assert response.status_code == 202
        assert response.data is None

    def test_a_get_service_kwargs_value_pins_each_row(self) -> None:
        def create(*, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [dict(row) for row in data]

        spec = ServiceSpec(
            service=create, permissions=_OPEN, validator=SerializerValidator(_PostIn), many=True
        )
        view = _view(ServiceCreateView, spec, get_service_kwargs=lambda self: {"title": "x"})
        response = view(factory.post("/", [{"title": "a"}, {"title": "b"}], format="json"))
        assert response.data == [{"title": "x"}, {"title": "x"}]

    def test_an_update_view_takes_a_many_spec_s_list_body_as_its_rows(self) -> None:
        """A ``many`` spec names no target selector, the kernel refusing one,
        since its list body is its rows: an update view mounts it, where a
        single-object spec naming no target is refused."""
        posts = [Post.objects.create(title="a"), Post.objects.create(title="b")]

        def retitle(*, data: list[dict[str, Any]]) -> list[Post]:
            for post, row in zip(posts, data, strict=True):
                post.title = row["title"]
                post.save(update_fields=["title"])
            return posts

        spec = ServiceSpec(
            service=retitle,
            permissions=_OPEN,
            validator=SerializerValidator(_PostIn),
            presenter=SerializerPresenter(_PostSerializer),
            many=True,
        )
        response = _view(ServiceUpdateView, spec)(
            factory.put("/", [{"title": "x"}, {"title": "y"}], format="json")
        )
        assert response.status_code == 200
        assert [row["title"] for row in response.data] == ["x", "y"]

    def test_a_service_error_maps_to_422(self) -> None:
        def boom(*, data: Any) -> None:
            raise ServiceError("no")

        spec = ServiceSpec(
            service=boom, permissions=_OPEN, validator=SerializerValidator(_PostIn), many=True
        )
        response = _view(ServiceCreateView, spec)(
            factory.post("/", [{"title": "a"}], format="json")
        )
        assert response.status_code == 422


class TestBulkCollectionTargets:
    def test_delete_over_a_collection_204(self) -> None:
        Post.objects.create(title="a")
        spec = ServiceSpec(
            service=delete_collection(Post),
            permissions=_OPEN,
            collection_selector_spec=_collection(),
            atomic=False,
        )
        assert _view(ServiceDeleteView, spec)(factory.delete("/")).status_code == 204
        assert not Post.objects.exists()

    def test_a_count_return_bumps_204_to_200(self) -> None:
        Post.objects.create(title="a")
        spec = ServiceSpec(
            service=lambda *, collection: {"deleted": collection.delete()[0]},
            permissions=_OPEN,
            collection_selector_spec=_collection(),
            atomic=False,
        )
        response = _view(ServiceDeleteView, spec)(factory.delete("/"))
        assert response.status_code == 200
        assert response.data == {"deleted": 1}

    def test_the_collection_selector_reads_a_declared_route_capture(self) -> None:
        mine = Author.objects.create(name="mine")
        Post.objects.create(title="kept", author=Author.objects.create(name="other"))
        Post.objects.create(title="gone", author=mine)
        spec = ServiceSpec(
            service=delete_collection(Post),
            permissions=_OPEN,
            collection_selector_spec=_collection(
                lambda *, author: Post.objects.filter(author_id=author),
                reads=Parameters.of(Parameter("author", "integer", required=True)),
            ),
            atomic=False,
        )
        assert (
            _view(ServiceDeleteView, spec)(factory.delete("/"), author=mine.pk).status_code == 204
        )
        assert list(Post.objects.values_list("title", flat=True)) == ["kept"]

    def test_a_route_capture_outranks_the_body_s_value(self) -> None:
        mine = Author.objects.create(name="mine")
        Post.objects.create(title="kept", author=Author.objects.create(name="other"))
        spec = ServiceSpec(
            service=delete_collection(Post),
            permissions=_OPEN,
            collection_selector_spec=_collection(
                lambda *, author: Post.objects.filter(author_id=author),
                reads=Parameters.of(Parameter("author", "integer", required=True)),
            ),
            atomic=False,
        )
        other = Post.objects.get().author_id
        request = factory.delete("/", {"author": other}, format="json")
        assert _view(ServiceDeleteView, spec)(request, author=mine.pk).status_code == 204
        assert Post.objects.filter(title="kept").exists()

    def test_bulk_update_over_a_collection_renders_a_list(self) -> None:
        Post.objects.create(title="a")
        Post.objects.create(title="b")

        def rename(*, collection: Any, data: dict[str, Any]) -> list[Post]:
            collection.update(title=data["title"])
            return list(Post.objects.order_by("id"))

        spec = ServiceSpec(
            service=rename,
            permissions=_OPEN,
            validator=SerializerValidator(_PostIn),
            collection_selector_spec=_collection(),
            presenter=SerializerPresenter(_PostSerializer),
            returns_many=True,
            atomic=False,
        )
        response = _view(ServiceUpdateView, spec)(factory.put("/", {"title": "z"}, format="json"))
        assert response.status_code == 200
        assert [row["title"] for row in response.data] == ["z", "z"]

    def test_a_single_row_collection_target_is_object_checked(self) -> None:
        post = Post.objects.create(title="a")

        class _DenyObject(BasePermission):
            def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
                return False

        spec = ServiceSpec(
            service=lambda *, collection: collection.delete(),
            permissions=_OPEN,
            collection_selector_spec=_collection(lambda: post),
            atomic=False,
        )
        view = _view(ServiceDeleteView, spec, permission_classes=[_DenyObject])
        assert view(factory.delete("/")).status_code == 403
        assert Post.objects.count() == 1

    def test_a_queryset_collection_target_is_untouched_by_the_guard(self) -> None:
        """Per-row permissions stay per-row: a set is not object-checked."""
        Post.objects.create(title="a")

        class _DenyObject(BasePermission):
            def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
                return False

        spec = ServiceSpec(
            service=delete_collection(Post),
            permissions=_OPEN,
            collection_selector_spec=_collection(),
            atomic=False,
        )
        view = _view(ServiceDeleteView, spec, permission_classes=[_DenyObject])
        assert view(factory.delete("/")).status_code == 204
        assert Post.objects.count() == 0
