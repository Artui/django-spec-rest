"""The query views serve a kernel spec's affordance answers as every transport renders them.

The rows' answers per view are held by ``test_selector_list_view`` and
``test_selector_retrieve_view``; this is the parity half: the body a browser
is served is the object the kernel's own ``present`` renders for any other
transport, and a subclass extending ``list`` keeps running. The viewset and
``selector_action`` sites are the viewsets' own.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db.models import Q, QuerySet
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
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorListView, SelectorRetrieveView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Post

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
UNPUBLISHED = Affordance(
    code="already_published", reason="This post is already published.", when=Q(published=False)
)
PUBLISH = ServiceSpec(service=lambda: None, permissions=_OPEN, affordances=[UNPUBLISHED])


class _PostOut(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()


def _posts() -> QuerySet[Post]:
    return Post.objects.order_by("id")


_LISTING = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=_posts,
    permissions=_OPEN,
    presenter=SerializerPresenter(_PostOut),
    affordances={"publish": PUBLISH},
)
_DETAIL = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, pk: Post.objects.filter(pk=pk),
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
    permissions=_OPEN,
    presenter=SerializerPresenter(_PostOut),
    affordances={"publish": PUBLISH},
)


def _body(response: Any) -> Any:
    response.render()
    return json.loads(response.content)


@pytest.fixture
def posts() -> tuple[Post, Post]:
    return Post.objects.create(title="draft"), Post.objects.create(title="out", published=True)


def _rendered_elsewhere(spec: SelectorSpec, **arguments: Any) -> Any:
    """What a transport with no view serves: the kernel's dispatch and present."""
    result = dispatch(spec, principal=AnonymousUser(), arguments=arguments)
    return json.loads(json.dumps(present(spec, result)))


def test_the_list_view_serves_what_another_transport_renders(posts: tuple[Post, Post]) -> None:
    view = type("_View", (SelectorListView,), {"spec": _LISTING})
    served = _body(view.as_view()(factory.get("/")))
    assert served == _rendered_elsewhere(_LISTING)
    assert [row["affordances"]["publish"]["available"] for row in served] == [True, False]


def test_the_retrieve_view_serves_what_another_transport_renders(
    posts: tuple[Post, Post],
) -> None:
    view = type("_View", (SelectorRetrieveView,), {"spec": _DETAIL})
    served = _body(view.as_view()(factory.get("/"), pk=str(posts[1].pk)))
    assert served == _rendered_elsewhere(_DETAIL, pk=posts[1].pk)
    assert served["affordances"]["publish"]["code"] == "already_published"


def test_the_list_view_keeps_a_subclass_list_override(posts: tuple[Post, Post]) -> None:
    """Declaring affordances must not route a request around the view's own ``list``."""

    class _View(SelectorListView):
        spec = _LISTING

        def list(self, request: Any, *args: Any, **kwargs: Any) -> Response:
            response = super().list(request, *args, **kwargs)
            response["X-Listed"] = "yes"
            return response

    response = _View.as_view()(factory.get("/"))
    assert response["X-Listed"] == "yes"
    assert len(_body(response)) == 2
