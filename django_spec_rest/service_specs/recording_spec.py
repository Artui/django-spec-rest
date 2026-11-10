from __future__ import annotations

import copy
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
    tuple[
        weakref.ref[KernelServiceSpec], dict[tuple[frozenset[str], bool, bool], KernelServiceSpec]
    ],
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


def recording_spec(spec: KernelSpec, *, lenient: bool = False) -> KernelSpec:
    """``spec``, or its twin whose providers the edge watches."""
    if not isinstance(spec, KernelServiceSpec):
        return spec
    changes: dict[str, Any] = {}
    names = frozenset[str]()
    if (
        not spec.many
        and spec.input_data is not None
        and isinstance(spec.validator, SerializerValidator)
    ):
        call_context = edge_call_state().call_context
        names = spec.validator.parameters(call_context=call_context).names() | seed_named_fields(
            spec.validator, call_context=call_context
        )
        if names:
            changes["input_data"] = _recording(spec.input_data, names)
    refusing = spec.kwargs is not None and isinstance(spec.validator, SerializerValidator)
    authored = bool(edge_call_state().author_values) and spec.validator is not None
    if refusing or authored:
        changes["kwargs"] = _providing(spec.kwargs, spec.validator if refusing else None)
    lenient = lenient and isinstance(spec.validator, SerializerValidator)
    if lenient:
        relaxed = copy.copy(cast(SerializerValidator, spec.validator))
        relaxed.lenient = True
        changes["validator"] = relaxed
    if not changes:
        return spec
    key = id(spec)
    with _LOCK:
        held = _RECORDING.get(key)
        if held is None or held[0]() is not spec:
            held = _RECORDING[key] = (
                weakref.ref(spec, lambda _dead: _RECORDING.pop(key, None)),
                {},
            )
        twin = held[1].get((names, authored, lenient))
        if twin is None:
            twin = held[1][names, authored, lenient] = spec.derive(**changes)
    return twin


def _providing(provider: Callable[..., Any] | None, validator: SerializerValidator | None) -> Any:
    """The twin's ``kwargs`` seat: ``provider``'s answer, checked, over the view hooks' values."""
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
    """The view hooks' values ``answer`` leaves standing, as the kernel's ``overlaid`` does."""
    return {
        name: value
        for name, value in edge_call_state().author_values.items()
        if name not in owned and answer.get(name, UNSET) is UNSET
    }


def _refuse_parameters(
    provider: Callable[..., Any], answer: Any, validator: SerializerValidator
) -> None:
    """Refuse ``answer`` where it names a parameter of ``validator``, a field's wire name."""
    if not isinstance(answer, Mapping):
        return
    named = sorted(
        name
        for name in validator.parameters(call_context=edge_call_state().call_context)
        .names()
        .intersection(answer)
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
    """Put ``answer``'s value for each of ``names`` into the body the edge holds for the call."""
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
