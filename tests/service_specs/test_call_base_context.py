"""``call_base_context``: the view's baseline, reused in an edge call only for its own request and view.

Each case runs inside one edge call, a POST to a live view whose service makes
kernel calls of its own, handing each a call context the edge did not build.
Those calls share the edge call's state, so they are where a held baseline
could be handed to a call it was not asked for: one per guard of
``call_base_context``, each failing without it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django_service_specs import ServiceSpec, Unrestricted, dispatch
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.views.server_value_calls import open_spec, post

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_SEEN: list[dict[str, Any]] = []


class _Records(serializers.Serializer):
    """Records the context each call validates under."""

    title = serializers.CharField()

    def validate(self, attrs: Any) -> Any:
        _SEEN.append(dict(self.context))
        return attrs


class _Plain:
    """A view answering no ``get_serializer_context``, so the baseline is DRF's shape over it."""


class _Named:
    """A view whose ``get_serializer_context`` answers a key naming it."""

    def __init__(self, who: str) -> None:
        self.who = who

    def get_serializer_context(self) -> dict[str, Any]:
        return {"who": self.who}


def _inner(serializer_context: Callable[..., Any] | None = None) -> ServiceSpec:
    return ServiceSpec(
        service=lambda *, data: None,
        permissions=(Unrestricted(),),
        validator=SerializerValidator(_Records, serializer_context=serializer_context),
        atomic=False,
    )


def _contexts(calls: list[tuple[ServiceSpec, dict[str, Any]]]) -> list[dict[str, Any]]:
    """The context each of ``calls`` validated under, made from inside one edge call."""

    def service(*, data: Any) -> None:
        for spec, call_context in calls:
            dispatch(
                spec,
                principal=AnonymousUser(),
                arguments={"title": "inner"},
                call_context=call_context,
            )

    _SEEN.clear()
    response = post(open_spec(service, _Records), {"title": "outer"})
    assert response.status_code == 204, response.data
    # The first is the edge call's own.
    return _SEEN[1:]


def test_a_call_carrying_another_view_is_answered_for_it() -> None:
    contexts = _contexts([(_inner(), {"view": _Named("one")}), (_inner(), {"view": _Named("two")})])

    assert [context["who"] for context in contexts] == ["one", "two"]


def test_a_call_carrying_another_request_is_answered_for_it() -> None:
    """One view, two requests the calls arrived on: each call's offline request
    is built around its own, and the baseline over the first is not the second's."""
    view = _Plain()
    first, second = (
        factory.get("/", HTTP_X_ARRIVED="first"),
        factory.get("/", HTTP_X_ARRIVED="second"),
    )

    contexts = _contexts(
        [
            (_inner(), {"request": first, "view": view}),
            (_inner(), {"request": second, "view": view}),
        ]
    )

    assert [context["request"].META["HTTP_X_ARRIVED"] for context in contexts] == [
        "first",
        "second",
    ]


def test_a_layer_one_call_lays_on_its_copy_never_reaches_the_next() -> None:
    """Three calls under one view and no request share the held baseline. The
    first two lay their spec's context layer on it, and the third, whose spec
    declares none, must not see it, whichever of the first two was handed the
    held dict itself rather than a copy."""
    view = _Plain()
    layered = _inner(serializer_context=lambda: {"layer": "first spec's"})

    contexts = _contexts(
        [(layered, {"view": view}), (layered, {"view": view}), (_inner(), {"view": view})]
    )

    assert [context.get("layer") for context in contexts] == ["first spec's", "first spec's", None]
