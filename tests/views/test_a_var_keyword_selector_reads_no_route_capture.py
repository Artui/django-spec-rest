"""A kernel selector taking a bare ``**kwargs`` is handed no route capture its spec does not declare.

The kernel hands a selector the arguments its ``reads`` declare and the seeds,
so a capture no read declares never reaches it: a retrieve scoped by that
capture finds no row, a ``404`` naming nothing, and a list selector filtering
only when the capture is present answers every row. Declaring the capture as a
read hands it on, coerced to the read's type.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.urls import path
from django_service_specs import Parameter, Parameters, SelectorKind, SelectorSpec, Unrestricted
from rest_framework import serializers
from rest_framework.test import APIClient

from django_spec_rest import SelectorListView, SelectorRetrieveView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Post

pytestmark = pytest.mark.django_db

_OPEN = (Unrestricted(),)
_PK = Parameters.of(Parameter("pk", "integer", required=True))


class _PostOut(serializers.ModelSerializer):
    class Meta:
        model = Post
        fields = ("id", "title")


def _by_kwargs(**kwargs: Any) -> Post | None:
    return Post.objects.filter(pk=kwargs.get("pk")).first()


def _filtered_when_present(**kwargs: Any) -> Any:
    queryset = Post.objects.order_by("id")
    if "pk" in kwargs:
        queryset = queryset.filter(pk=kwargs["pk"])
    return queryset


def _spec(kind: SelectorKind, selector: Any, reads: Parameters | None = None) -> SelectorSpec:
    return SelectorSpec(
        kind=kind,
        selector=selector,
        reads=reads or Parameters(),
        permissions=_OPEN,
        presenter=SerializerPresenter(_PostOut),
    )


class _Retrieve(SelectorRetrieveView):
    spec = _spec(SelectorKind.RETRIEVE, _by_kwargs)


class _RetrieveDeclared(SelectorRetrieveView):
    spec = _spec(SelectorKind.RETRIEVE, _by_kwargs, _PK)


class _List(SelectorListView):
    spec = _spec(SelectorKind.LIST, _filtered_when_present)


class _ListDeclared(SelectorListView):
    spec = _spec(SelectorKind.LIST, _filtered_when_present, _PK)


class _StringRead(SelectorRetrieveView):
    spec = _spec(
        SelectorKind.RETRIEVE, _by_kwargs, Parameters.of(Parameter("pk", "string", required=True))
    )


urlpatterns = [
    path("undeclared/<int:pk>/", _Retrieve.as_view()),
    path("declared/<int:pk>/", _RetrieveDeclared.as_view()),
    path("list/<int:pk>/", _List.as_view()),
    path("list-declared/<int:pk>/", _ListDeclared.as_view()),
    path("string/<int:pk>/", _StringRead.as_view()),
]


@pytest.fixture
def posts() -> tuple[Post, Post]:
    return Post.objects.create(title="a"), Post.objects.create(title="b")


@pytest.mark.urls(__name__)
class TestAVarKeywordSelector:
    def test_an_undeclared_capture_never_reaches_it(self, posts: tuple[Post, Post]) -> None:
        response = APIClient().get(f"/undeclared/{posts[0].pk}/")
        assert response.status_code == 404
        assert "pk" not in str(response.data)

    def test_a_declared_capture_reaches_it(self, posts: tuple[Post, Post]) -> None:
        response = APIClient().get(f"/declared/{posts[1].pk}/")
        assert response.data == {"id": posts[1].pk, "title": "b"}

    def test_a_list_filtering_only_when_the_capture_is_present_answers_every_row(
        self, posts: tuple[Post, Post]
    ) -> None:
        response = APIClient().get(f"/list/{posts[0].pk}/")
        assert [row["title"] for row in response.data] == ["a", "b"]

    def test_a_list_scoped_by_a_declared_capture_answers_its_rows(
        self, posts: tuple[Post, Post]
    ) -> None:
        response = APIClient().get(f"/list-declared/{posts[0].pk}/")
        assert [row["title"] for row in response.data] == ["a"]

    def test_a_string_read_of_an_int_route_s_capture_is_refused(
        self, posts: tuple[Post, Post]
    ) -> None:
        """The converter yields an ``int``, and a string read takes no number:
        the read's type has to be the one the route yields."""
        response = APIClient().get(f"/string/{posts[0].pk}/")
        assert response.status_code == 400
        assert "pk" in response.data
