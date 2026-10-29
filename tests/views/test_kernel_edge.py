"""The kernel route's edge: the predicate, and its sync and async cores agreeing.

``tests/test_sync_async_parity.py`` holds the drfs cores against each other;
the kernel route's pair is held here the same way, each case driven through
``dispatch_kernel_spec`` and ``adispatch_kernel_spec`` with one outcome
expected, and the two signatures compared.
"""

from __future__ import annotations

import gc
import inspect
import weakref
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import DataclassValidator, DispatchError, ServiceSpec, Unrestricted
from rest_framework import serializers
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest import SelectorKind, SelectorSpec
from django_spec_rest import ServiceSpec as DrfsServiceSpec
from django_spec_rest.dispatch.kernel_edge import (
    adispatch_kernel_spec,
    dispatch_kernel_spec,
    runs_on_kernel,
)
from django_spec_rest.dispatch.kernel_refusals import KernelDispatchRefused
from django_spec_rest.service_specs.invalid_arguments import InvalidArguments
from django_spec_rest.service_specs.recording_spec import recording_spec
from django_spec_rest.service_specs.seed_named_fields import seed_named_fields
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.service_specs.utils import EDGE_CALL
from django_spec_rest.views.utils import view_call_context
from tests.views.test_kernel_views import _CREATE, _ONE, _AuthorInput, _CreateView

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


def test_a_kernel_service_spec_runs_on_the_kernel() -> None:
    assert runs_on_kernel(_CREATE)


def test_a_kernel_selector_spec_runs_on_the_kernel() -> None:
    assert runs_on_kernel(_ONE)


def test_a_drfs_spec_does_not_run_on_the_kernel() -> None:
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


def test_a_read_only_field_named_like_a_seed_is_none_the_body_sends() -> None:
    """A read-only field takes nothing from a body, so no seed-named field is
    held for it, whatever its name; only the writable ones are."""

    class _Input(serializers.Serializer):
        title = serializers.CharField()
        user = serializers.IntegerField(read_only=True)
        result = serializers.IntegerField()

    assert seed_named_fields(SerializerValidator(_Input)) == frozenset({"result"})


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


def _sync_then_state(spec: Any, **kwargs: Any) -> Any:
    # Every outcome is a case; the state after it is the assertion.
    with suppress(Exception):
        dispatch_kernel_spec(spec, **kwargs)
    return EDGE_CALL.get()


async def _async_then_state(spec: Any, **kwargs: Any) -> Any:
    # Read inside the coroutine that awaited the core, so the state is the
    # context the core ran in, not one ``async_to_sync`` copied back.
    with suppress(Exception):
        await adispatch_kernel_spec(spec, **kwargs)
    return EDGE_CALL.get()


@pytest.mark.parametrize("outcome", ["returned", "refused", "raised"])
@pytest.mark.parametrize(
    "core", [_sync_then_state, async_to_sync(_async_then_state)], ids=["sync", "async"]
)
def test_the_edge_s_state_ends_with_the_call(core: Callable[..., Any], outcome: str) -> None:
    """The state the edge sets for a call is gone after it, however the call
    ended, so the next call on the same thread or task starts from none."""

    class _Input(serializers.Serializer):
        title = serializers.CharField()
        user = serializers.IntegerField()

    def service(*, data: Any) -> None:
        if outcome == "raised":
            raise RuntimeError("boom")
        if outcome == "refused":
            raise DispatchError("Not this way.")

    spec = ServiceSpec(service=service, permissions=_OPEN, validator=SerializerValidator(_Input))
    assert core(spec, **_parts({"title": "t", "user": 1})) is None


class _UserPk(serializers.Serializer):
    title = serializers.CharField()
    user = serializers.IntegerField(required=False)


@CORES
def test_the_provider_is_called_once_and_its_value_binds(core: Callable[..., Any]) -> None:
    """The recording twin's provider is the spec's own, bound from the pool by
    its signature and asked once, and its value for a seed-named field is what
    the serializer binds, over what the client sent for it."""
    calls: list[Any] = []
    received: dict[str, Any] = {}

    def user_pk(*, user: Any) -> dict[str, Any]:
        calls.append(user)
        return {"user": user.pk}

    principal = User.objects.create(username="ada")
    spec = ServiceSpec(
        service=lambda *, data: received.update(data),
        permissions=_OPEN,
        validator=SerializerValidator(_UserPk),
        input_data=user_pk,
    )
    core(spec, **_parts({"title": "t", "user": 7}, user=principal))
    assert calls == [principal]
    assert received == {"title": "t", "user": principal.pk}


def test_a_spec_s_recording_twin_is_built_once_and_dropped_with_it() -> None:
    spec = ServiceSpec(
        service=lambda *, data: None,
        permissions=_OPEN,
        validator=SerializerValidator(_UserPk),
        input_data=lambda: {},
    )
    twin = recording_spec(spec)
    assert twin is not spec
    assert recording_spec(spec) is twin
    assert twin.validator is spec.validator
    held = weakref.ref(twin)
    del spec, twin
    gc.collect()
    assert held() is None


def test_a_spec_with_nothing_to_record_is_dispatched_as_it_is() -> None:
    def spec(**kwargs: Any) -> ServiceSpec:
        return ServiceSpec(service=lambda *, data: None, permissions=_OPEN, **kwargs)

    provided = {"validator": SerializerValidator(_UserPk), "input_data": lambda: {}}
    for unrecorded in (
        _ONE,
        spec(many=True, **provided),
        spec(validator=SerializerValidator(_UserPk)),
        spec(validator=SerializerValidator(_AuthorInput), input_data=lambda: {}),
    ):
        assert recording_spec(unrecorded) is unrecorded
    recorded = spec(**provided)
    assert recording_spec(recorded) is not recorded


def test_a_provider_answering_no_mapping_is_the_kernel_s_to_refuse() -> None:
    spec = ServiceSpec(
        service=lambda *, data: None,
        permissions=_OPEN,
        validator=SerializerValidator(_UserPk),
        input_data=lambda: None,
    )
    with pytest.raises(ImproperlyConfigured, match="returned NoneType"):
        dispatch_kernel_spec(spec, **_parts({"title": "t"}))


def test_the_two_cores_take_the_same_arguments() -> None:
    def shape(fn: Callable[..., Any]) -> list[tuple[str, Any, Any]]:
        return [
            (name, param.kind, param.default)
            for name, param in inspect.signature(fn).parameters.items()
        ]

    assert shape(dispatch_kernel_spec) == shape(adispatch_kernel_spec)
