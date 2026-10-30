"""A target lookup reading a name that is also a writable input field.

A lookup by ``title`` beside a body ``title`` declares two sources for one name,
and a kernel spec declares one source per name, so its ``parameters()`` is
refused in the kernel's words, and with it ``as_view()``. The lookup reads a name of its own instead, which the route captures
and the client's body never moves.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
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

_factory = APIRequestFactory()
_TWICE = r"Parameters \['title'\] are declared by two sources"


class _TitleIn(serializers.Serializer):
    title = serializers.CharField()


class _UpdateView(ServiceUpdateView):
    permission_classes = []


def _spec(seen: dict[str, Any], *, lookup_reads: str) -> ServiceSpec:
    def selector(**pool: Any) -> Any:
        # ``**`` takes the whole pool (``user``, ``progress``), so only the
        # two reads are kept.
        scope = {name: pool[name] for name in ("pk", lookup_reads)}
        seen["lookup"] = scope
        return Post.objects.get(pk=scope["pk"], title=scope[lookup_reads])

    def service(*, instance: Any, data: Any, title: str = "svc-default") -> Any:
        seen.update(title=title, data=dict(data))
        return instance

    return ServiceSpec(
        service=service,
        validator=SerializerValidator(_TitleIn),
        presenter=SerializerPresenter(PostSerializer),
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=selector,
            reads=Parameters(
                (
                    Parameter("pk", "integer", required=True),
                    Parameter(lookup_reads, "string", required=True),
                )
            ),
        ),
        permissions=(Unrestricted(),),
        atomic=False,
    )


def test_the_spec_s_parameters_refuse_the_name_declared_twice() -> None:
    with pytest.raises(ImproperlyConfigured, match=_TWICE):
        _spec({}, lookup_reads="title").parameters()


def test_as_view_refuses_it_in_the_kernel_s_words() -> None:
    with pytest.raises(ImproperlyConfigured, match=_TWICE):
        type("_View", (_UpdateView,), {"spec": _spec({}, lookup_reads="title")}).as_view()


def _put(spec: ServiceSpec, body: dict[str, Any], *, fmt: str = "json", **route: Any) -> Any:
    view = type("_View", (_UpdateView,), {"spec": spec}).as_view()
    return view(_factory.put("/", body, format=fmt), **route)


@pytest.mark.django_db
@pytest.mark.parametrize("fmt", ["json", "multipart"])
def test_the_route_scopes_the_lookup_and_the_body_fills_the_field(fmt: str) -> None:
    seen: dict[str, Any] = {}
    post = Post.objects.create(title="old")

    response = _put(
        _spec(seen, lookup_reads="current"), {"title": "new"}, fmt=fmt, pk=post.pk, current="old"
    )

    assert response.status_code == 200, response.data
    assert seen == {
        "lookup": {"pk": post.pk, "current": "old"},
        "title": "new",
        "data": {"title": "new"},
    }


@pytest.mark.django_db
def test_a_body_value_never_moves_a_captured_lookup() -> None:
    seen: dict[str, Any] = {}
    post = Post.objects.create(title="old")
    Post.objects.create(title="other")

    response = _put(
        _spec(seen, lookup_reads="current"),
        {"title": "new", "pk": 0, "current": "other"},
        pk=post.pk,
        current="old",
    )

    assert response.status_code == 200, response.data
    assert seen["lookup"] == {"pk": post.pk, "current": "old"}


@pytest.mark.django_db
def test_a_lookup_read_the_route_does_not_capture_is_never_the_body_s() -> None:
    """A target lookup's read comes from the route or the query string, so a
    body naming it chooses nothing: with neither sending it, the required
    read is missing, and the call is refused before the lookup runs."""
    seen: dict[str, Any] = {}
    post = Post.objects.create(title="old")

    response = _put(
        _spec(seen, lookup_reads="current"), {"title": "new", "current": "old"}, pk=post.pk
    )

    assert response.status_code == 400
    assert "current" in response.data
    assert seen == {}
    post.refresh_from_db()
    assert post.title == "old"


@pytest.mark.django_db
def test_with_neither_the_lookup_s_required_read_is_refused_as_missing() -> None:
    seen: dict[str, Any] = {}
    post = Post.objects.create(title="old")

    response = _put(_spec(seen, lookup_reads="current"), {"title": "new"}, pk=post.pk)

    assert response.status_code == 400
    assert "current" in response.data
    assert seen == {}
