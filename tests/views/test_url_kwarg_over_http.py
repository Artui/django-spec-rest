"""The route-capture rule on a kernel selector spec, over HTTP.

A capture the spec declares as a read is its argument, coerced to the read's
type and over whatever the query string sends under the same name. A capture
it does not declare is no argument: the selector is not handed it, it stays on
``view.kwargs`` for DRF's own machinery (a permission class, a queryset), and
nothing refuses it, under either unknown-argument policy. drfs' ``UrlKwarg``
declaration drops with its spec types; a kernel read is the declaration.
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
    UnknownArguments,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.test import APIClient

from django_spec_rest import SelectorListView
from django_spec_rest.dispatch import kernel_edge
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Author, Post

pytestmark = pytest.mark.django_db

_OPEN = (Unrestricted(),)
_SEEN: dict[str, Any] = {}


class _PostOut(serializers.Serializer):
    title = serializers.CharField()


class _ReadsTheRoute(BasePermission):
    """DRF's own machinery reads every capture off ``view.kwargs``."""

    def has_permission(self, request: Any, view: Any) -> bool:
        _SEEN["permission"] = dict(view.kwargs)
        return True


def _posts_of(**kwargs: Any) -> Any:
    _SEEN["selector"] = kwargs
    return Post.objects.filter(author_id=kwargs["author_pk"]).order_by("id")


class _NestedPosts(SelectorListView):
    """``/authors/<author_pk>/tags/<tag>/posts/``: one capture declared, one not."""

    permission_classes = [_ReadsTheRoute]
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=_posts_of,
        reads=Parameters.of(Parameter("author_pk", "integer")),
        permissions=_OPEN,
        presenter=SerializerPresenter(_PostOut),
    )


urlpatterns = [
    path("authors/<str:author_pk>/tags/<str:tag>/posts/", _NestedPosts.as_view()),
]


@pytest.fixture
def authors() -> tuple[Author, Author]:
    a1, a2 = Author.objects.create(name="a1"), Author.objects.create(name="a2")
    Post.objects.create(title="a1-post", author=a1)
    Post.objects.create(title="a2-post", author=a2)
    _SEEN.clear()
    return a1, a2


@pytest.mark.urls(__name__)
class TestTheRouteCaptureRule:
    @pytest.mark.parametrize("policy", [UnknownArguments.REJECT, UnknownArguments.IGNORE])
    def test_an_undeclared_capture_is_no_argument_and_stays_on_view_kwargs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        authors: tuple[Author, Author],
        policy: UnknownArguments,
    ) -> None:
        monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", policy)
        response = APIClient().get(f"/authors/{authors[0].pk}/tags/news/posts/")
        # Not refused, under either policy, and no ``ImproperlyConfigured``.
        assert response.status_code == 200, response.data
        # The declared capture and the call's seeds, never the undeclared one.
        assert _SEEN["selector"]["author_pk"] == authors[0].pk
        assert "tag" not in _SEEN["selector"]
        assert _SEEN["permission"] == {"author_pk": str(authors[0].pk), "tag": "news"}

    def test_a_declared_capture_arrives_coerced_to_its_read_s_type(
        self, authors: tuple[Author, Author]
    ) -> None:
        """The ``str`` converter hands ``"1"``; the integer read makes it ``1``."""
        APIClient().get(f"/authors/{authors[0].pk}/tags/news/posts/")
        assert _SEEN["selector"]["author_pk"] == authors[0].pk
        assert isinstance(_SEEN["selector"]["author_pk"], int)

    def test_the_route_scopes_the_selector(self, authors: tuple[Author, Author]) -> None:
        response = APIClient().get(f"/authors/{authors[1].pk}/tags/news/posts/")
        assert response.data == [{"title": "a2-post"}]

    def test_the_route_outranks_the_query_string(self, authors: tuple[Author, Author]) -> None:
        """A client naming the declared capture in the query string cannot
        move the scope the route sets."""
        response = APIClient().get(
            f"/authors/{authors[0].pk}/tags/news/posts/?author_pk={authors[1].pk}"
        )
        assert response.data == [{"title": "a1-post"}]

    def test_an_uncoercible_capture_is_refused_under_its_name(
        self, authors: tuple[Author, Author]
    ) -> None:
        response = APIClient().get("/authors/nope/tags/news/posts/")
        assert response.status_code == 400
        assert list(response.data) == ["author_pk"]
        assert "selector" not in _SEEN
