"""What the DRF edge carries for its own machinery never reaches a kernel spec's callables.

The edge keeps its state for a call - the body the serializer binds, the view's
serializer context layers, the descriptions it builds - in a context variable,
never in the call's pool. So a callable taking a bare ``**kwargs`` is handed
the kernel's pool alone: ``user``, ``progress``, the Validator's values and
what the stage itself binds, with no name of the edge's, and, by the kernel's
own rule, neither ``request``, ``view`` nor ``call_context``, which are handed
by name only. Each case runs over a live view, and the service case through
both cores.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django.db.models import QuerySet
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

from django_spec_rest import SelectorListView, SelectorRetrieveView, ServiceCreateView
from django_spec_rest.dispatch.kernel_edge import adispatch_kernel_spec, dispatch_kernel_spec
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.views.utils import view_call_context
from tests.testapp.models import Post

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
SEEN: dict[str, list[str]] = {}
# The names the kernel hands by name only, never to a catch-all.
_BY_NAME_ONLY = {"request", "view", "call_context"}


def _private(names: list[str]) -> list[str]:
    return [name for name in names if name.startswith("_")]


def _edge_s(names: list[str]) -> list[str]:
    """The names no stage of the kernel's pool carries: the edge's, or one handed by name only."""
    return [name for name in names if name.startswith("_") or name in _BY_NAME_ONLY]


class _TitleIn(serializers.Serializer):
    title = serializers.CharField()


class _TitleOut(serializers.Serializer):
    title = serializers.CharField()


def _recording(stage: str, answer: Any = None) -> Callable[..., Any]:
    def callable_(**rest: Any) -> Any:
        SEEN[stage] = sorted(rest)
        return answer

    return callable_


_SERVICE = ServiceSpec(
    service=_recording("service", answer={"title": "t"}),
    permissions=_OPEN,
    validator=SerializerValidator(_TitleIn, serializer_context=_recording("input", answer={})),
    presenter=SerializerPresenter(_TitleOut, serializer_context=_recording("output", answer={})),
    preconditions=(_recording("precondition"),),
    atomic=False,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    SEEN.clear()


class _CreateView(ServiceCreateView):
    """A create view over a kernel spec, carrying a view hook of each kind."""

    spec = _SERVICE

    def get_input_serializer_context(self) -> dict[str, Any]:
        return {"layer": 1}


def test_over_http_a_bare_kwargs_stage_sees_no_edge_machinery() -> None:
    response = _CreateView.as_view()(_factory.post("/", {"title": "t"}, format="json"))

    assert response.status_code == 201, response.data
    assert set(SEEN) == {"service", "input", "output", "precondition"}
    for stage in ("service", "precondition"):
        assert _edge_s(SEEN[stage]) == [], stage
    # A seat's own context callable is this package's, and its pool holds the
    # serializer's ``request`` and ``view`` by design; nothing of the edge's.
    for stage in ("input", "output"):
        assert _private(SEEN[stage]) == [], stage
        assert "call_context" not in SEEN[stage], stage
    assert {"user", "data"} <= set(SEEN["service"])


def _parts() -> dict[str, Any]:
    view = _CreateView()
    view.args, view.kwargs, view.format_kwarg = (), {}, None
    request = view.initialize_request(_factory.post("/", {"title": "t"}, format="json"))
    view.request = request
    return {"view": view, "request": request, "call_context": view_call_context(view, request)}


@pytest.mark.parametrize(
    "core",
    [dispatch_kernel_spec, async_to_sync(adispatch_kernel_spec)],
    ids=["sync", "async"],
)
def test_through_either_core_a_bare_kwargs_service_sees_no_edge_machinery(
    core: Callable[..., Any],
) -> None:
    core(_SERVICE, **_parts())

    assert _edge_s(SEEN["service"]) == []
    assert _private(SEEN["input"]) == []


def _rows(**rest: Any) -> QuerySet[Post]:
    SEEN["selector"] = sorted(rest)
    return Post.objects.all()


def _row(*, pk: int, **rest: Any) -> Post:
    SEEN["selector"] = sorted(rest)
    return Post.objects.get(pk=pk)


class _Echo(serializers.Serializer):
    title = serializers.CharField()


@pytest.mark.parametrize(
    ("base", "spec", "by_pk"),
    [
        (
            SelectorListView,
            SelectorSpec(kind=SelectorKind.LIST, selector=_rows, permissions=_OPEN),
            False,
        ),
        (
            SelectorRetrieveView,
            SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=_row,
                reads=Parameters.of(Parameter("pk", "integer", required=True)),
                permissions=_OPEN,
            ),
            True,
        ),
    ],
    ids=["list", "retrieve"],
)
def test_over_http_a_bare_kwargs_selector_sees_no_edge_machinery(
    base: type, spec: SelectorSpec, by_pk: bool
) -> None:
    post = Post.objects.create(title="p")
    view = type("_View", (base,), {"spec": spec, "serializer_class": _Echo}).as_view()

    response = view(_factory.get("/"), **({"pk": str(post.pk)} if by_pk else {}))

    assert response.status_code == 200, response.data
    assert _edge_s(SEEN["selector"]) == []
