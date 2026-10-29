"""A seat's serializer context callable that queries runs off the loop under ``adispatch``.

A spec is written once and served over both cores, so its callables are sync.
One calling the ORM from the event loop raises ``SynchronousOnlyOperation``, a
failure only the async core shows, and only for the callables that happen to
query. The documented use of a ``SerializerValidator``'s ``serializer_context``
is exactly that, a scoping lookup against another table, so each case here
queries inside it and asserts that what it read reached the serializer that
validated: on the loop it raises, in the thread-sensitive executor it does not.

The presenter's callable runs in the render step, ``apresent``, whose own
off-loop cases are the presenter's.
"""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import ServiceSpec, Unrestricted
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView
from django_spec_rest.dispatch.kernel_edge import adispatch_kernel_spec
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.views.utils import view_call_context
from tests.testapp.models import Post

pytestmark = pytest.mark.django_db(transaction=True)

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


def _scope_provider() -> dict[str, Any]:
    """The documented headline use: a scoping lookup against another table."""
    return {"seen": Post.objects.count()}


class _TitleIn(serializers.Serializer):
    """Hands on, as a value, what the context callable read."""

    title = serializers.CharField()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        return {**attrs, "seen": self.context["seen"]}


def _parts(body: Any) -> dict[str, Any]:
    view = ServiceCreateView()
    view.args, view.kwargs, view.format_kwarg = (), {}, None
    request = view.initialize_request(factory.post("/", body, format="json"))
    view.request = request
    return {"view": view, "request": request, "call_context": view_call_context(view, request)}


async def test_a_validator_s_context_callable_that_queries() -> None:
    await Post.objects.acreate(title="a")
    spec = ServiceSpec(
        service=lambda *, data: data,
        permissions=_OPEN,
        validator=SerializerValidator(_TitleIn, serializer_context=_scope_provider),
        atomic=False,
    )

    result = await adispatch_kernel_spec(spec, **_parts({"title": "x"}))

    assert result.value == {"title": "x", "seen": 1}


async def test_a_many_validator_s_context_callable_that_queries() -> None:
    await Post.objects.acreate(title="a")
    spec = ServiceSpec(
        service=lambda *, data: data,
        permissions=_OPEN,
        many=True,
        validator=SerializerValidator(_TitleIn, serializer_context=_scope_provider),
        atomic=False,
    )

    result = await adispatch_kernel_spec(spec, **_parts([{"title": "x"}, {"title": "y"}]))

    assert result.value == [{"title": "x", "seen": 1}, {"title": "y", "seen": 1}]
