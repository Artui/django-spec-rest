"""A kernel selector spec's declared read is read off the query string, over HTTP.

drfs' ``QueryParam`` declaration drops with its spec types; a kernel read is
the declaration, read through ``flat_arguments`` and coerced to its type. The
query string is the request's own: a permission class reads it before the
dispatch, and the dispatch writes nothing back onto it.
"""

from __future__ import annotations

from typing import Any

import pytest
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
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorListView, SelectorRetrieveView
from django_spec_rest.dispatch import kernel_edge
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Post

pytestmark = pytest.mark.django_db

_OPEN = (Unrestricted(),)
factory = APIRequestFactory()


class _PostOut(serializers.Serializer):
    title = serializers.CharField()


class _NotUnpublished(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return request.query_params.get("published") != "false"


def _posts(*, published: bool) -> Any:
    return Post.objects.filter(published=published).order_by("id")


def _view(**attrs: Any) -> Any:
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=_posts,
        reads=Parameters.of(Parameter("published", "boolean", required=True)),
        permissions=_OPEN,
        presenter=SerializerPresenter(_PostOut),
    )
    return type("_View", (SelectorListView,), {"spec": spec, **attrs}).as_view()


@pytest.fixture
def posts() -> None:
    Post.objects.create(title="draft")
    Post.objects.create(title="out", published=True)


def test_the_query_string_is_the_read_on_a_live_view(posts: None) -> None:
    assert _view()(factory.get("/?published=true")).data == [{"title": "out"}]
    assert _view()(factory.get("/?published=false")).data == [{"title": "draft"}]


def test_the_permission_reads_the_request_s_own_query_string(posts: None) -> None:
    view = _view(permission_classes=[_NotUnpublished])
    assert view(factory.get("/?published=false")).status_code == 403
    assert view(factory.get("/?published=true")).status_code == 200


def test_a_missing_required_read_is_refused_under_its_name(posts: None) -> None:
    response = _view()(factory.get("/"))
    assert response.status_code == 400
    assert list(response.data) == ["published"]


@pytest.mark.parametrize("policy", [UnknownArguments.REJECT, UnknownArguments.IGNORE])
def test_a_missing_row_beside_an_unknown_key(
    monkeypatch: pytest.MonkeyPatch, policy: UnknownArguments
) -> None:
    """Under ``REJECT`` the kernel checks the arguments before it looks the row
    up, so an unknown key beside a missing row answers 400, where drfs
    answered the miss first, 404. Under ``IGNORE`` the key is dropped and the
    miss is the answer."""
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", policy)
    spec = SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Post.objects.filter(pk=pk).first(),
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
        permissions=_OPEN,
        presenter=SerializerPresenter(_PostOut),
    )
    view = type("_View", (SelectorRetrieveView,), {"spec": spec}).as_view()
    response = view(factory.get("/?nope=1"), pk="999")
    if policy is UnknownArguments.REJECT:
        assert response.status_code == 400
        assert list(response.data) == ["nope"]
    else:
        assert response.status_code == 404
