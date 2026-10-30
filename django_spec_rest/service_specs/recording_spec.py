"""``recording_spec`` - the twin of a kernel spec the HTTP edge dispatches in its place.

The kernel route (``dispatch/kernel_edge.py``) dispatches it in the spec's
place. Its ``input_data`` puts its answer for each field onto the body the
serializer binds, and records it as the server's value for the field, since the
kernel merges that answer into its arguments alone; and its ``kwargs`` refuses
an answer naming a field's wire name, which would reach the service
unvalidated.
"""

from __future__ import annotations

import functools
import threading
import weakref
from collections.abc import Callable, Mapping
from typing import Any, cast

from django.core.exceptions import ImproperlyConfigured
from django.http import QueryDict
from django.utils.datastructures import MultiValueDict
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from django_service_specs.types.unset import UNSET

from django_spec_rest.service_specs.seed_named_fields import seed_named_fields
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.service_specs.utils import edge_call_state, write_form_value

KernelSpec = KernelServiceSpec | KernelSelectorSpec


_RECORDING: dict[
    int,
    tuple[weakref.ref[KernelServiceSpec], dict[tuple[frozenset[str], bool], KernelServiceSpec]],
] = {}
"""Each spec's recording twins, by the spec's identity and then by the names each records.

Keyed by ``id`` because a spec's dataclass hash reads every field, some of
which need not hash. Each entry holds a weak reference to its spec, whose
callback drops the entry when the spec dies, and a read serves a twin only
while that reference still names the spec asked about, as the kernel's own
``kernel_spec`` cache holds its compiled specs. Beneath the spec, by the
writable fields the call's serializer declares and whether the call carries a
view hook's values for the ``kwargs`` seat: a request-scoped
``get_fields`` declares different ones per caller, so the first call must not
decide what a later one records
(test_kernel_edge's test_one_spec_s_twin_records_what_each_call_s_serializer_declares)."""

_LOCK = threading.Lock()


def recording_spec(spec: KernelSpec) -> KernelSpec:
    """``spec``, or its twin whose providers the edge watches.

    Two seats, each wrapped only where it has something to watch:
    ``input_data``, which puts its answer for each field onto the body, and
    ``kwargs``, whose answer naming a parameter of a ``SerializerValidator``
    is refused (``_refuse_parameters``) and which hands back a view hook's
    values beneath that answer (``_providing``).

    The serializer binds the request's body rather than the kernel's
    arguments, and the kernel merges the provider's answer into its arguments
    alone, so without the twin the provider's value for a field would never
    reach the serializer, and a client sending the field would bind its own
    value in the server's place (test_the_provider_s_value_outranks_the_client_s),
    one a second route of the serializer's put back included
    (test_server_value_over_a_second_route's
    test_input_data_outranks_a_second_route_over_http). The twin's provider is
    the spec's own, wrapped so its signature, and so the pool it is bound from,
    is the spec's, and called once per call as the spec's is
    (test_kernel_edge's test_the_provider_is_called_once_and_its_value_binds).
    What it records goes into the body the edge holds for the Validator and
    into the call's server values (``_record``).

    **Asked inside the edge's call**, with its state set, since the names are
    the writable fields of the serializer described for the call: with the
    call's request, so a ``get_fields`` reading ``self.context["request"]``
    describes rather than raising, and declares the fields this caller sends
    (test_kernel_edge's
    test_the_twin_records_the_fields_the_call_s_own_serializer_declares). The
    async core asks it in the thread it reads the call in, since describing
    may query (test_the_async_core_builds_the_twin_off_the_loop).

    Built once per spec and set of names, since ``derive`` re-runs the spec's
    checks. Only a single-object service spec with a ``kwargs`` provider over
    a ``SerializerValidator``, an ``input_data`` provider over a
    ``SerializerValidator`` with a writable field, or a Validator and a call
    carrying a view hook's values, has one; the kernel refuses an ``async`` provider when
    the spec is built, so the wrapper is sync alone. The twin shares every
    seat but those two, so presenting the result through the view's own
    spec is unchanged. A kernel ``Grant`` covers a call only for the spec it
    was minted for, by identity, so a caller passing one must mint it for, or
    compare it against, the twin.
    """
    # One arc to coverage, so each disjunct is named: a selector spec and a
    # ``many`` spec by test_kernel_edge's
    # test_a_spec_with_nothing_to_record_is_dispatched_as_it_is, which also
    # holds a spec with no provider and one with no writable field.
    if not isinstance(spec, KernelServiceSpec) or spec.many:
        return spec
    changes: dict[str, Any] = {}
    names = frozenset[str]()
    # One arc to coverage, so each conjunct is named, both by test_kernel_edge's
    # test_a_spec_with_nothing_to_record_is_dispatched_as_it_is: a spec with no
    # ``input_data`` provider, and a Validator that is no serializer's, whose
    # input is the kernel's arguments; so is a serializer no caller's value
    # reaches, with no name to record.
    if spec.input_data is not None and isinstance(spec.validator, SerializerValidator):
        names = spec.validator.parameters().names() | seed_named_fields(spec.validator)
        if names:
            changes["input_data"] = _recording(spec.input_data, names)
    # One arc to coverage, so each conjunct is named: a spec with no ``kwargs``
    # provider by test_a_spec_with_nothing_to_record_is_dispatched_as_it_is,
    # and a Validator that is no serializer's, which declares what it takes
    # itself, by test_another_validator_s_kwargs_provider_is_not_checked.
    refusing = spec.kwargs is not None and isinstance(spec.validator, SerializerValidator)
    # The view hooks' values go beneath the spec's own provider in its seat,
    # where they outrank what the Validator computes, as on drfs; in the
    # kernel's overlay they sit beneath it. Only where a Validator computes
    # anything: a saving rather than a check, since without a Validator the
    # overlay already reaches the service with the same values, held by
    # test_kernel_edge's test_a_spec_with_nothing_to_record_is_dispatched_as_it_is
    # with the call carrying no hook value.
    authored = bool(edge_call_state().author_values) and spec.validator is not None
    if refusing or authored:
        changes["kwargs"] = _providing(spec.kwargs, spec.validator if refusing else None)
    if not changes:
        return spec
    key = id(spec)
    with _LOCK:
        held = _RECORDING.get(key)
        # One arc to coverage: ``held[0]() is not spec`` refuses an entry a
        # reused ``id`` left under another spec (test_kernel_edge's
        # test_a_stale_entry_under_a_live_spec_s_id_is_not_its_twin); the
        # weakref callback is what normally keeps one from existing
        # (test_a_spec_s_recording_twin_is_built_once_and_dropped_with_it).
        if held is None or held[0]() is not spec:
            held = _RECORDING[key] = (
                weakref.ref(spec, lambda _dead: _RECORDING.pop(key, None)),
                {},
            )
        twin = held[1].get((names, authored))
        if twin is None:
            twin = held[1][names, authored] = spec.derive(**changes)
    return twin


def _providing(provider: Callable[..., Any] | None, validator: SerializerValidator | None) -> Any:
    """The twin's ``kwargs`` seat: ``provider``'s answer, checked, over the view hooks' values.

    Where ``validator`` is given, an answer naming one of its parameters is
    refused (``_refuse_parameters``). The values a view's
    ``get_service_kwargs`` named no parameter with (``EdgeCallState.author_values``)
    go beneath the answer as the kernel lays its overlay beneath a provider
    (``_beneath``), so they outrank what the Validator computes as the spec's
    own provider does (test_author_values_outrank_the_validator's
    test_a_view_hooks_value_outranks_the_validators_over_http).
    """
    owned = frozenset[str]()
    if provider is not None and (keys := provider_keys(provider)) is not None:
        owned = keys.filled

    def providing(*args: Any, **kwargs: Any) -> Any:
        answer = {} if provider is None else provider(*args, **kwargs)
        if validator is not None:
            _refuse_parameters(cast(Callable[..., Any], provider), answer, validator)
        if not isinstance(answer, Mapping):
            return answer
        return {**answer, **_beneath(answer, owned)}

    return providing if provider is None else functools.wraps(provider)(providing)


def _beneath(answer: Mapping[str, Any], owned: frozenset[str]) -> dict[str, Any]:
    """The view hooks' values ``answer`` leaves standing, as the kernel's ``overlaid`` leaves its overlay's.

    A key the answer gives a value outranks the hook's
    (test_the_spec_s_provider_outranks_a_view_hook_for_one_key). A key the
    provider is annotated to fill and may not decline is the provider's alone,
    so a hook's value for it is dropped
    (test_a_key_the_typed_provider_owns_is_never_a_view_hook_s), while one it
    may decline and declines falls to the hook
    (test_a_key_the_provider_declines_falls_to_a_view_hook). A hook's
    ``UNSET`` is passed on, which the kernel takes as the key declined
    (test_a_view_hook_s_unset_supplies_nothing).
    """
    return {
        name: value
        for name, value in edge_call_state().author_values.items()
        if name not in owned and answer.get(name, UNSET) is UNSET
    }


def _refuse_parameters(
    provider: Callable[..., Any], answer: Any, validator: SerializerValidator
) -> None:
    """Refuse ``answer`` where it names a parameter of ``validator``, a field's wire name.

    The kernel merges a ``kwargs`` provider's answer into the service's pool
    alone, after the Validator, so a value under a field's wire name reaches
    the service unvalidated, where drfs validated it as the field's: another
    user's primary key under a queryset scoped to the caller was taken. The
    kernel refuses a typed provider annotated to fill such a key when the spec
    is built; an untyped one shows its keys only when it is called, so the
    first request answering one is refused, loudly, as the author's error
    (test_a_kwargs_value_named_like_a_field_is_refused). A key it declines
    with ``UNSET`` names nothing (test_a_declined_wire_name_is_not_refused),
    and a key named like a field's ``source`` is no parameter, so it stays the
    service's (test_a_kwargs_value_named_like_a_source_is_the_service_s). An
    answer that is no mapping is left for the kernel to refuse in its own words
    (test_a_kwargs_answer_that_is_no_mapping_is_the_kernel_s_to_refuse).
    """
    if not isinstance(answer, Mapping):
        return
    named = sorted(
        name
        for name in validator.parameters().names().intersection(answer)
        if answer[name] is not UNSET
    )
    if named:
        label = getattr(provider, "__qualname__", repr(provider))
        raise ImproperlyConfigured(
            f"ServiceSpec.kwargs ({label}) answered {', '.join(map(repr, named))}, which "
            f"{'names a field' if len(named) == 1 else 'name fields'} of the spec's Validator: "
            "a kwargs value reaches the service unvalidated. Fill a Validator field from "
            "ServiceSpec.input_data, which the Validator validates."
        )


def _recording(provider: Callable[..., Any], names: frozenset[str]) -> Any:
    @functools.wraps(provider)
    def recording(*args: Any, **kwargs: Any) -> Any:
        answer = provider(*args, **kwargs)
        _record(answer, names)
        return answer

    return recording


def _record(answer: Any, names: frozenset[str]) -> None:
    """Put ``answer``'s value for each of ``names`` into the body the edge holds for the call.

    Over the body, a list on a form body through ``setlist``
    (``write_form_value``), and into the call's ``server_values``, over a view
    hook's value for the same field, since the kernel merges the provider's
    answer over the arguments: the Validator validates that value for the
    field on its own and lays it back over whatever a second route made of the
    key (test_server_value_over_a_second_route's
    test_input_data_outranks_a_second_route_over_http). The body is copied
    before it is written to, since the edge hands the request's own on where
    it put nothing there.

    A value the provider declines with ``UNSET`` is no answer: what the body
    holds for the name stands, which ``kernel_arguments`` has already emptied
    of a key the provider owns
    (test_an_owned_field_it_declines_is_absent_not_the_client_s,
    test_a_declinable_field_it_declines_stays_the_client_s). The twin is
    dispatched by the kernel route's two cores alone, inside the call whose state holds
    that body, so the body is always there. An answer that is no mapping is
    left for the kernel to refuse in its own words
    (test_kernel_edge's test_a_provider_answering_no_mapping_is_the_kernel_s_to_refuse).
    """
    if not isinstance(answer, Mapping):
        return
    put = {name: answer[name] for name in names.intersection(answer) if answer[name] is not UNSET}
    if not put:
        return
    state = edge_call_state()
    validator, held = cast(tuple[Any, Any], state.validator_input)
    body = held.copy() if isinstance(held, MultiValueDict) else dict(held)
    server = dict(state.server_values)
    for name, value in put.items():
        if isinstance(body, QueryDict):
            write_form_value(body, name, value)
        else:
            body[name] = value
        server[name] = value
    state.validator_input = (validator, body)
    state.server_values = server
