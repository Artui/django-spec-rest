"""``recording_spec`` - a kernel spec whose ``input_data`` records its answer for the seed-named fields.

The kernel route (``dispatch/kernel_edge.py``) dispatches it in the spec's
place, so the serializer binds the provider's value for a field the kernel
never hands a Validator (``seed_named_fields``).
"""

from __future__ import annotations

import functools
import threading
import weakref
from collections.abc import Callable, Mapping
from typing import Any, cast

from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from django_service_specs.types.unset import UNSET

from django_spec_rest.service_specs.seed_named_fields import seed_named_fields
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
    """``spec``, or its twin whose ``input_data`` records its answer for the seed-named fields.

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
    checks. Only a single-object service spec with a provider and a
    seed-named field has one; the kernel refuses an ``async`` provider when
    the spec is built, so the wrapper is sync alone. The twin shares every
    seat but the provider, so presenting the result through the view's own
    spec is unchanged. A kernel ``Grant`` covers a call only for the spec it
    was minted for, by identity, so a caller passing one must mint it for, or
    compare it against, the twin.
    """
    # One arc to coverage, so each disjunct is named: a selector spec and a
    # ``many`` spec by test_kernel_edge's
    # test_a_spec_with_nothing_to_record_is_dispatched_as_it_is, which also
    # holds a spec with no provider and one with no seed-named field.
    if not isinstance(spec, KernelServiceSpec) or spec.many or spec.input_data is None:
        return spec
    names = seed_named_fields(spec.validator)
    if not names:
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
            twin = held[1][names] = spec.derive(input_data=_recording(spec.input_data, names))
    return twin


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
