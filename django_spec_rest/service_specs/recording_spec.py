"""``recording_spec`` - the twin of a kernel spec the HTTP edge dispatches in its place.

The kernel route (``dispatch/kernel_edge.py``) dispatches it in the spec's
place. Its ``input_data`` records its answer for the seed-named fields, so the
serializer binds the provider's value for a field the kernel never hands a
Validator (``seed_named_fields``), and its ``kwargs`` refuses an answer naming a
field's wire name, which would reach the service unvalidated.
"""

from __future__ import annotations

import functools
import threading
import weakref
from collections.abc import Callable, Mapping
from typing import Any, cast

from django.core.exceptions import ImproperlyConfigured
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from django_service_specs.types.unset import UNSET

from django_spec_rest.service_specs.seed_named_fields import seed_named_fields
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.service_specs.utils import edge_call_state

KernelSpec = KernelServiceSpec | KernelSelectorSpec


_RECORDING: dict[
    int, tuple[weakref.ref[KernelServiceSpec], dict[frozenset[str], KernelServiceSpec]]
] = {}
"""Each spec's recording twins, by the spec's identity and then by the names each records.

Keyed by ``id`` because a spec's dataclass hash reads every field, some of
which need not hash. Each entry holds a weak reference to its spec, whose
callback drops the entry when the spec dies, and a read serves a twin only
while that reference still names the spec asked about, as the kernel's own
``kernel_spec`` cache holds its compiled specs. Beneath the spec, by the
seed-named fields the call's serializer declares: a request-scoped
``get_fields`` declares different ones per caller, so the first call must not
decide what a later one records
(test_kernel_edge's test_one_spec_s_twin_records_what_each_call_s_serializer_declares)."""

_LOCK = threading.Lock()


def recording_spec(spec: KernelSpec) -> KernelSpec:
    """``spec``, or its twin whose providers the edge watches.

    Two seats, each wrapped only where it has something to watch:
    ``input_data``, which records its answer for the seed-named fields, and
    ``kwargs``, whose answer naming a parameter of a ``SerializerValidator``
    is refused (``_refuse_parameters``).

    The kernel hands a Validator only the ``input_data`` keys its
    ``parameters()`` declare, and a seed-named field is none of them, so the
    provider's value for one would never reach the serializer, and a client
    sending the field would bind its own value in the server's place
    (test_the_provider_s_value_outranks_the_client_s). The twin's provider is
    the spec's own, wrapped so its signature, and so the pool it is bound from,
    is the spec's, and called once per call as the spec's is
    (test_kernel_edge's test_the_provider_is_called_once_and_its_value_binds).
    What it records goes into the body the edge holds for the Validator
    (``_record``).

    **Asked inside the edge's call**, with its state set, since the names are
    the seed-named fields of the serializer described for the call: with the
    call's request, so a ``get_fields`` reading ``self.context["request"]``
    describes rather than raising, and declares the fields this caller sends
    (test_kernel_edge's
    test_the_twin_records_the_fields_the_call_s_own_serializer_declares). The
    async core asks it in the thread it reads the call in, since describing
    may query (test_the_async_core_builds_the_twin_off_the_loop).

    Built once per spec and set of names, since ``derive`` re-runs the spec's
    checks. Only a single-object service spec with a ``kwargs`` provider over
    a ``SerializerValidator``, or an ``input_data`` provider and a seed-named
    field, has one; the kernel refuses an ``async`` provider when
    the spec is built, so the wrapper is sync alone. The twin shares every
    seat but those two, so presenting the result through the view's own
    spec is unchanged. A kernel ``Grant`` covers a call only for the spec it
    was minted for, by identity, so a caller passing one must mint it for, or
    compare it against, the twin.
    """
    # One arc to coverage, so each disjunct is named: a selector spec and a
    # ``many`` spec by test_kernel_edge's
    # test_a_spec_with_nothing_to_record_is_dispatched_as_it_is, which also
    # holds a spec with no provider and one with no seed-named field.
    if not isinstance(spec, KernelServiceSpec) or spec.many:
        return spec
    changes: dict[str, Any] = {}
    names = frozenset[str]()
    if spec.input_data is not None:
        names = seed_named_fields(spec.validator)
        if names:
            changes["input_data"] = _recording(spec.input_data, names)
    # One arc to coverage, so each conjunct is named: a spec with no ``kwargs``
    # provider by test_a_spec_with_nothing_to_record_is_dispatched_as_it_is,
    # and a Validator that is no serializer's, which declares what it takes
    # itself, by test_another_validator_s_kwargs_provider_is_not_checked.
    if spec.kwargs is not None and isinstance(spec.validator, SerializerValidator):
        changes["kwargs"] = _refusing_parameters(spec.kwargs, spec.validator)
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
        twin = held[1].get(names)
        if twin is None:
            twin = held[1][names] = spec.derive(**changes)
    return twin


def _refusing_parameters(provider: Callable[..., Any], validator: SerializerValidator) -> Any:
    @functools.wraps(provider)
    def refusing(*args: Any, **kwargs: Any) -> Any:
        answer = provider(*args, **kwargs)
        _refuse_parameters(provider, answer, validator)
        return answer

    return refusing


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
    body = cast(tuple[Any, dict[str, Any]], edge_call_state().validator_input)[1]
    for name in names.intersection(answer):
        if answer[name] is not UNSET:
            body[name] = answer[name]
