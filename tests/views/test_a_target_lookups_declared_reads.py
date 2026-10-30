"""A target lookup's declared reads come from the route and the query string, never the body.

A kernel spec declares a read as a ``Parameter``, with no ``UrlKwarg`` or
``QueryParam`` to say where it comes from. On the kernel route a target
lookup's reads choose the row a write reaches, so the edge reads them from the
route's captures and the query string alone, the route's over the query
string's, and drops a body key of a read's name (``kernel_arguments``): a
client's body never chooses the row, as drfs read a lookup's ``QueryParam``
from the query string alone. Nothing the body sends is written onto
``view.kwargs`` or ``request.query_params``, which the view's permission
classes have already read. Off HTTP a kernel spec is the kernel's own
``dispatch``, which has no view to read, so drfs' offline-view cases have no
counterpart here.
"""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceUpdateView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Post
from tests.testapp.serializers import PostSerializer

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()


class _BodyIn(serializers.Serializer):
    body = serializers.CharField(required=False)


class _UpdateView(ServiceUpdateView):
    permission_classes = []


def _spec(seen: dict[str, Any]) -> ServiceSpec:
    def selector(*, pk: int, q: str = "D-q", org: str = "D-org") -> Any:
        seen.update(q=q, org=org)
        return Post.objects.get(pk=pk)

    def service(*, instance: Any, data: Any, view: Any) -> Any:
        # ``view`` is the call's own seed, so what the call left on it is read
        # after the lookup ran.
        seen.update(kwargs=dict(view.kwargs), query=dict(view.request.query_params))
        return instance

    return ServiceSpec(
        service=service,
        validator=SerializerValidator(_BodyIn),
        presenter=SerializerPresenter(PostSerializer),
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=selector,
            reads=Parameters(
                (
                    Parameter("pk", "integer", required=True),
                    Parameter("q", "string"),
                    Parameter("org", "string"),
                )
            ),
        ),
        permissions=(Unrestricted(),),
        atomic=False,
    )


_SENT = {"body": "x", "q": "from-body", "org": "from-body"}


def _put(seen: dict[str, Any], url: str, body: dict[str, Any], fmt: str, **route: Any) -> Any:
    view = type("_View", (_UpdateView,), {"spec": _spec(seen)}).as_view()
    return view(_factory.put(url, body, format=fmt), **route)


@pytest.mark.parametrize("fmt", ["json", "multipart"])
def test_a_route_capture_of_a_lookup_read_goes_over_the_query_string(fmt: str) -> None:
    seen: dict[str, Any] = {}
    post = Post.objects.create(title="a")

    response = _put(seen, "/?q=from-query&org=from-query", _SENT, fmt, pk=post.pk, org="from-route")

    assert response.status_code == 200, response.data
    assert (seen["q"], seen["org"]) == ("from-query", "from-route")


@pytest.mark.parametrize("fmt", ["json", "multipart"])
def test_the_query_string_fills_a_lookup_read_the_route_does_not_capture(fmt: str) -> None:
    seen: dict[str, Any] = {}
    post = Post.objects.create(title="a")

    response = _put(seen, "/?q=from-query&org=from-query", {"body": "x"}, fmt, pk=post.pk)

    assert response.status_code == 200, response.data
    assert (seen["q"], seen["org"]) == ("from-query", "from-query")


@pytest.mark.parametrize("fmt", ["json", "multipart"])
def test_a_body_value_never_reaches_the_lookup_the_route_or_the_query_string(fmt: str) -> None:
    seen: dict[str, Any] = {}
    post = Post.objects.create(title="a")

    response = _put(seen, "/", _SENT, fmt, pk=post.pk)

    assert response.status_code == 200, response.data
    assert (seen["q"], seen["org"]) == ("D-q", "D-org")
    assert seen["kwargs"] == {"pk": post.pk}
    assert seen["query"] == {}


@pytest.mark.parametrize("fmt", ["json", "multipart"])
def test_a_body_value_never_chooses_the_row(fmt: str) -> None:
    """The body's ``pk`` names another row; the route's is the one found."""
    seen: dict[str, Any] = {}
    post = Post.objects.create(title="a")
    other = Post.objects.create(title="b")

    response = _put(seen, "/", {"body": "x", "pk": other.pk}, fmt, pk=post.pk)

    assert response.status_code == 200, response.data
    assert response.data["id"] == post.pk
