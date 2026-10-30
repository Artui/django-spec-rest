"""The kernel route's edge: the predicate, and its sync and async cores agreeing.

Each case is driven through ``dispatch_kernel_spec`` and
``adispatch_kernel_spec`` with one outcome expected, and the two signatures
are compared.
"""

from __future__ import annotations

import asyncio
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
from django.http import QueryDict
from django_service_specs import (
    DataclassValidator,
    DispatchError,
    Parameter,
    Parameters,
    SelectorKind,
    ServiceSpec,
    UnknownArguments,
    Unrestricted,
)
from django_service_specs import SelectorSpec as KernelSelectorSpec
from rest_framework import serializers
from rest_framework.parsers import JSONParser
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest.dispatch import kernel_edge
from django_spec_rest.dispatch.kernel_edge import (
    adispatch_kernel_spec,
    dispatch_kernel_spec,
)
from django_spec_rest.dispatch.kernel_refusals import KernelDispatchRefused
from django_spec_rest.service_specs import recording_spec as recording_spec_module
from django_spec_rest.service_specs.drf_invalid_arguments import DRFInvalidArguments
from django_spec_rest.service_specs.recording_spec import recording_spec
from django_spec_rest.service_specs.seed_named_fields import seed_named_fields
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.service_specs.utils import EDGE_CALL
from django_spec_rest.types.view_hooks import ViewHooks
from django_spec_rest.views.utils import view_call_context
from tests.testapp.models import Author
from tests.views.test_kernel_views import _CREATE, _ONE, _AuthorInput, _CreateView

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


def test_another_validator_s_body_is_stripped_of_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only a ``SerializerValidator`` leaves a writable field out of its
    parameters; any other Validator's body is the kernel's arguments as sent,
    so under ``REJECT`` a ``user`` it does not declare is refused."""
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", UnknownArguments.REJECT)

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
    with pytest.raises(DRFInvalidArguments) as raised:
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


def test_a_stale_entry_under_a_live_spec_s_id_is_not_its_twin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An entry whose weak reference names another spec, as a reused ``id``
    would leave one, is rebuilt rather than served."""

    def spec() -> ServiceSpec:
        return ServiceSpec(
            service=lambda *, data: None,
            permissions=_OPEN,
            validator=SerializerValidator(_UserPk),
            input_data=lambda: {},
        )

    live, other = spec(), spec()
    stale = recording_spec(other)
    monkeypatch.setitem(
        recording_spec_module._RECORDING,
        id(live),
        (weakref.ref(other), {(frozenset({"title", "user"}), False): stale}),
    )
    twin = recording_spec(live)
    assert twin is not stale
    assert twin is not live


class _ReadsOnly(serializers.Serializer):
    """No field a caller's value reaches, so ``input_data`` fills none."""

    id = serializers.IntegerField(read_only=True)


@dataclass
class _TitleIn:
    title: str


def test_a_spec_with_nothing_to_record_is_dispatched_as_it_is() -> None:
    def spec(**kwargs: Any) -> ServiceSpec:
        return ServiceSpec(service=lambda *, data: None, permissions=_OPEN, **kwargs)

    provided = {"validator": SerializerValidator(_AuthorInput), "input_data": lambda: {}}
    for unrecorded in (
        _ONE,
        spec(many=True, **provided),
        spec(validator=SerializerValidator(_UserPk)),
        spec(validator=SerializerValidator(_ReadsOnly), input_data=lambda: {}),
        spec(validator=DataclassValidator(_TitleIn), input_data=lambda: {}),
    ):
        assert recording_spec(unrecorded) is unrecorded
    recorded = spec(**provided)
    assert recording_spec(recorded) is not recorded


class _StaffSeeds(serializers.Serializer):
    """Declares a seed-named ``user`` for every caller, and a ``result`` for staff only.

    Reads ``self.context["request"].user`` as a DRF serializer may, so it can
    only be described with the call's request."""

    title = serializers.CharField()
    user = serializers.CharField(required=False)

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        if self.context["request"].user.is_staff:
            fields["result"] = serializers.CharField(required=False)
        return fields


def _staff_seeds(received: dict[str, Any]) -> ServiceSpec:
    return ServiceSpec(
        service=lambda *, data: received.update(data),
        permissions=_OPEN,
        validator=SerializerValidator(_StaffSeeds),
        input_data=lambda: {"user": "server-user", "result": "server-result"},
    )


@CORES
def test_the_twin_records_the_fields_the_call_s_own_serializer_declares(
    core: Callable[..., Any],
) -> None:
    """The twin is built inside the call, from the serializer described with
    the call's request: a ``get_fields`` reading the request's user describes,
    where unbound it would raise, and a staff caller's ``result`` field is
    the provider's, where a description with no request declares none and
    the client's value would bind."""
    received: dict[str, Any] = {}
    staff = User.objects.create(username="staff", is_staff=True)
    body = {"title": "t", "user": "client-user", "result": "client-result"}
    core(_staff_seeds(received), **_parts(body, user=staff))
    assert received == {"title": "t", "user": "server-user", "result": "server-result"}


def test_one_spec_s_twin_records_what_each_call_s_serializer_declares() -> None:
    """The first call's fields do not decide what a later call records: a
    caller declaring ``user`` alone, then a staff caller declaring ``result``
    too, each bind the provider's value for every field their own serializer
    declares."""
    received: dict[str, Any] = {}
    spec = _staff_seeds(received)
    plain = User.objects.create(username="plain")
    staff = User.objects.create(username="staff", is_staff=True)
    dispatch_kernel_spec(spec, **_parts({"title": "t", "user": "client-user"}, user=plain))
    assert received == {"title": "t", "user": "server-user"}
    received.clear()
    body = {"title": "t", "user": "client-user", "result": "client-result"}
    dispatch_kernel_spec(spec, **_parts(body, user=staff))
    assert received == {"title": "t", "user": "server-user", "result": "server-result"}


@pytest.mark.django_db(transaction=True)
def test_the_async_core_builds_the_twin_off_the_loop() -> None:
    """Building the twin describes the serializer, whose ``get_fields`` may
    query, so the async core builds it in the thread it reads the call in."""
    on_loop: list[bool] = []

    class _Querying(serializers.Serializer):
        title = serializers.CharField()
        user = serializers.CharField(required=False)

        def get_fields(self) -> dict[str, serializers.Field]:
            on_loop.append(_on_the_loop())
            User.objects.count()
            return super().get_fields()

    received: dict[str, Any] = {}
    spec = ServiceSpec(
        service=lambda *, data: received.update(data),
        permissions=_OPEN,
        validator=SerializerValidator(_Querying),
        input_data=lambda: {"user": "server-user"},
        atomic=False,
    )
    _async(spec, **_parts({"title": "t", "user": "client-user"}))
    assert received == {"title": "t", "user": "server-user"}
    assert on_loop
    assert True not in on_loop


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


_PK = Parameters.of(Parameter("pk", "integer", required=True))


def _rename_spec() -> ServiceSpec:
    return ServiceSpec(
        service=lambda *, instance: instance.name,
        permissions=_OPEN,
        instance_selector_spec=KernelSelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
            reads=_PK,
            permissions=_OPEN,
        ),
    )


def _with_route(parts: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    parts["view"].kwargs = kwargs
    return parts


@CORES
def test_with_no_on_target_the_kernel_s_own_lookup_finds_the_row(
    core: Callable[..., Any],
) -> None:
    author = Author.objects.create(name="Ada")
    result = core(_rename_spec(), **_with_route(_parts({}), pk=author.pk))
    assert result.value == "Ada"


@CORES
def test_on_target_is_asked_of_the_row_before_the_service(core: Callable[..., Any]) -> None:
    author = Author.objects.create(name="Ada")
    asked: list[Any] = []
    result = core(_rename_spec(), on_target=asked.append, **_with_route(_parts({}), pk=author.pk))
    assert (asked, result.value) == ([author], "Ada")


@CORES
def test_a_row_the_lookup_misses_is_not_found_and_asks_nothing(
    core: Callable[..., Any],
) -> None:
    asked: list[Any] = []
    result = core(_rename_spec(), on_target=asked.append, **_with_route(_parts({}), pk=999))
    assert (result.kind, asked) == ("not_found", [])


@CORES
def test_a_row_the_kernel_s_lookup_misses_carries_no_output_layer(
    core: Callable[..., Any],
) -> None:
    """A missing row's answer has no presentation context to put the view's
    output layer on, so it comes back as the kernel gave it."""
    hooks = ViewHooks(output_serializer_context=lambda context: {"shown": True})
    result = core(_rename_spec(), view_hooks=hooks, **_with_route(_parts({}), pk=999))
    assert (result.kind, result.context) == ("not_found", None)


def _named_list(seen: list[str]) -> KernelSelectorSpec:
    return KernelSelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda *, name: seen.append(name) or Author.objects.none(),
        reads=Parameters.of(Parameter("name", "string", required=True)),
        permissions=_OPEN,
    )


def _listing(query_string: str) -> dict[str, Any]:
    parts = _parts({})
    parts["request"] = parts["view"].initialize_request(factory.get(f"/?{query_string}"))
    return parts


_POLICIES = pytest.mark.parametrize("policy", [UnknownArguments.REJECT, UnknownArguments.IGNORE])


@CORES
@_POLICIES
def test_a_query_handed_over_is_read_in_place_of_the_request_s(
    core: Callable[..., Any], monkeypatch: pytest.MonkeyPatch, policy: UnknownArguments
) -> None:
    """A selector spec reads the query string its caller hands, so a key the
    view's own pagination reads and the request carries is never the spec's
    argument, under either policy."""
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", policy)
    seen: list[str] = []
    core(_named_list(seen), query=QueryDict("name=handed"), **_listing("name=sent&page=2"))
    assert seen == ["handed"]


class _OptionalTitle(serializers.Serializer):
    title = serializers.CharField(required=False)


@CORES
def test_an_undeclared_body_key_is_dropped_by_default_on_either_core(
    core: Callable[..., Any],
) -> None:
    """Both cores pass the edge's one policy, ``IGNORE``, set nowhere here."""
    received: list[dict[str, Any]] = []
    spec = ServiceSpec(
        service=lambda *, data: received.append(data),
        permissions=_OPEN,
        validator=SerializerValidator(_OptionalTitle),
    )
    core(spec, **_parts({"title": "t", "id": 1}))
    assert received == [{"title": "t"}]


@CORES
@_POLICIES
def test_with_no_query_handed_the_request_s_is_read(
    core: Callable[..., Any], monkeypatch: pytest.MonkeyPatch, policy: UnknownArguments
) -> None:
    """Today's behaviour: the request's query string is the arguments, so its
    ``page`` is refused under ``REJECT`` and dropped under ``IGNORE``."""
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", policy)
    seen: list[str] = []
    parts = _listing("name=sent&page=2")
    if policy is UnknownArguments.REJECT:
        with pytest.raises(DRFInvalidArguments) as refused:
            core(_named_list(seen), **parts)
        assert list(refused.value.detail) == ["page"]
        assert seen == []
    else:
        core(_named_list(seen), **parts)
        assert seen == ["sent"]


def test_the_async_core_reads_the_body_off_the_loop() -> None:
    """Parsing ``request.data`` reads the request's stream, which may block, so
    the async core reads it in a worker thread rather than on the event loop."""
    on_loop: list[bool] = []

    class _Recording(JSONParser):
        def parse(self, *args: Any, **kwargs: Any) -> Any:
            try:
                asyncio.get_running_loop()
                on_loop.append(True)
            except RuntimeError:
                on_loop.append(False)
            return super().parse(*args, **kwargs)

    parts = _parts({"name": "Ada"})
    parts["request"].parsers = [_Recording()]
    result = _async(_CREATE, **parts)
    assert result.value.name == "Ada"
    assert on_loop == [False]


def _on_the_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def test_the_async_core_describes_the_input_serializer_off_the_loop() -> None:
    """A serializer is described with the call's request, and a ``get_fields``
    may query through it, so the async core builds every description in a
    worker thread rather than on the event loop."""
    on_loop: list[bool] = []

    class _Recording(serializers.Serializer):
        name = serializers.CharField()

        def get_fields(self) -> dict[str, serializers.Field]:
            on_loop.append(_on_the_loop())
            return super().get_fields()

    spec = ServiceSpec(
        service=lambda *, data: data["name"],
        permissions=_OPEN,
        validator=SerializerValidator(_Recording),
    )
    assert _async(spec, **_parts({"name": "Ada"})).value == "Ada"
    assert on_loop
    assert True not in on_loop
