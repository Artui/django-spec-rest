"""The kernel route's edge: the predicate, and its sync and async cores agreeing.

``tests/test_sync_async_parity.py`` holds the drfs cores against each other;
the kernel route's pair is held here the same way, each case driven through
``dispatch_kernel_spec`` and ``adispatch_kernel_spec`` with one outcome
expected, and the two signatures compared.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth.models import User
from django_service_specs import DataclassValidator, DispatchError, ServiceSpec, Unrestricted
from rest_framework import serializers
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest import SelectorKind, SelectorSpec
from django_spec_rest import ServiceSpec as DrfsServiceSpec
from django_spec_rest.dispatch.kernel_edge import (
    KernelDispatchRefused,
    adispatch_kernel_spec,
    dispatch_kernel_spec,
    runs_on_kernel,
)
from django_spec_rest.service_specs.invalid_arguments import InvalidArguments
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.views.utils import view_call_context
from tests.views.test_kernel_views import _CREATE, _CreateView

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


def test_a_drfs_spec_does_not_run_on_the_kernel() -> None:
    assert runs_on_kernel(_CREATE)
    assert not runs_on_kernel(DrfsServiceSpec(service=lambda: None))
    assert not runs_on_kernel(SelectorSpec(kind=SelectorKind.LIST, selector=lambda: []))
    assert not runs_on_kernel(None)


def test_another_validator_s_body_is_stripped_of_nothing() -> None:
    """Only a ``SerializerValidator`` leaves a writable field out of its
    parameters; any other Validator's body is the kernel's arguments as sent,
    so a ``user`` it does not declare is refused."""

    @dataclass
    class _Input:
        title: str

    spec = ServiceSpec(
        service=lambda: None, permissions=_OPEN, validator=DataclassValidator(_Input)
    )
    view = type("_View", (_CreateView,), {"spec": spec}).as_view()
    response = view(factory.post("/", {"title": "t", "user": 1}, format="json"))
    assert response.status_code == 400
    assert "Unknown argument." in str(response.data["user"])


def _sync(spec: Any, **kwargs: Any) -> Any:
    return dispatch_kernel_spec(spec, **kwargs)


def _async(spec: Any, **kwargs: Any) -> Any:
    return async_to_sync(adispatch_kernel_spec)(spec, **kwargs)


CORES = pytest.mark.parametrize("core", [_sync, _async], ids=["sync", "async"])


def _parts(body: Any, *, user: Any = None) -> dict[str, Any]:
    view = _CreateView()
    django_request = factory.post("/", body, format="json")
    if user is not None:
        force_authenticate(django_request, user=user)
    view.args, view.kwargs, view.format_kwarg = (), {}, None
    request = view.initialize_request(django_request)
    view.request = request
    return {"view": view, "request": request, "call_context": view_call_context(view, request)}


@CORES
def test_a_create_runs_and_hands_back_the_service_s_row(core: Callable[..., Any]) -> None:
    result = core(_CREATE, **_parts({"name": "Ada"}))
    assert result.kind == "instance"
    assert result.value.name == "Ada"


@CORES
def test_the_call_s_context_is_the_dict_handed_over(core: Callable[..., Any]) -> None:
    seen: dict[str, Any] = {}

    def service(*, call_context: Any, request: Any, view: Any) -> None:
        seen.update(call_context=call_context, request=request, view=view)

    parts = _parts({})
    core(ServiceSpec(service=service, permissions=_OPEN), **parts)
    assert seen["call_context"] is parts["call_context"]
    assert seen["request"] is parts["request"]
    assert seen["view"] is parts["view"]


@CORES
def test_a_seed_named_field_validates_from_the_body(core: Callable[..., Any]) -> None:
    class _Input(serializers.Serializer):
        title = serializers.CharField()
        user = serializers.IntegerField()

    received: dict[str, Any] = {}
    principal = User.objects.create(username="ada")
    spec = ServiceSpec(
        service=lambda *, data, user: received.update(data=data, user=user),
        permissions=_OPEN,
        validator=SerializerValidator(_Input),
    )
    core(spec, **_parts({"title": "t", "user": 7}, user=principal))
    assert received == {"data": {"title": "t", "user": 7}, "user": principal}


@CORES
def test_a_refused_argument_leaves_as_drf_s_400(core: Callable[..., Any]) -> None:
    with pytest.raises(InvalidArguments) as raised:
        core(_CREATE, **_parts({}))
    assert raised.value.detail["name"][0].code == "required"


@CORES
def test_a_bare_dispatch_error_leaves_as_the_route_s_400(core: Callable[..., Any]) -> None:
    def service() -> None:
        raise DispatchError("Not this way.")

    with pytest.raises(KernelDispatchRefused) as raised:
        core(ServiceSpec(service=service, permissions=_OPEN), **_parts({}))
    assert raised.value.detail == "Not this way."


def test_the_two_cores_take_the_same_arguments() -> None:
    def shape(fn: Callable[..., Any]) -> list[tuple[str, Any, Any]]:
        return [
            (name, param.kind, param.default)
            for name, param in inspect.signature(fn).parameters.items()
        ]

    assert shape(dispatch_kernel_spec) == shape(adispatch_kernel_spec)
