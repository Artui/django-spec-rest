from __future__ import annotations

import threading
import weakref
from collections.abc import Callable
from typing import Any

from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec

from django_spec_rest.service_specs.serializer_validator import SerializerValidator

_Variant = tuple[bool | None, bool]

# id(source) -> (a weak reference to it, its variants by key). Keyed by identity
# for the reason ``kernel_spec`` gives: a frozen dataclass compares by its fields,
# so two equal declarations would share one variant, and a ``Grant`` binds the
# compiled spec by identity. The callback drops a source's variants with it.
_VARIANTS: dict[int, tuple[weakref.ref[Any], dict[_Variant, Any]]] = {}
_LOCK = threading.Lock()


def kernel_spec_variant(
    spec: KernelServiceSpec | KernelSelectorSpec,
    *,
    partial: bool | None = None,
    lenient: bool = False,
) -> KernelServiceSpec | KernelSelectorSpec:
    """``spec`` as one request of the DRF edge dispatches it, derived once per variant."""
    key: _Variant = (partial, lenient)
    if key == (None, False):
        return kernel_spec(spec)
    return _derived(spec, key)


def _held(spec: Any, key: _Variant, build: Callable[[], Any]) -> Any:
    """The variant ``key`` of ``spec``, built by ``build`` on first use and held while ``spec`` lives."""
    with _LOCK:
        held = _VARIANTS.get(id(spec))
        if held is None:
            source_id = id(spec)
            source = weakref.ref(spec, lambda _dead: _VARIANTS.pop(source_id, None))
            held = _VARIANTS[source_id] = (source, {})
        variants = held[1]
        compiled = variants.get(key)
        if compiled is None:
            compiled = variants[key] = build()
    return compiled


def _derived(
    spec: KernelServiceSpec | KernelSelectorSpec, key: _Variant
) -> KernelServiceSpec | KernelSelectorSpec:
    """A kernel spec's variant: ``partial`` and ``lenient`` derived, and nothing else asked of it."""
    partial, lenient = key
    changes = _kernel_changes(spec, partial, lenient) if isinstance(spec, KernelServiceSpec) else {}
    if not changes:
        return spec
    return _held(spec, key, lambda: spec.derive(**changes))


def _kernel_changes(spec: KernelServiceSpec, partial: bool | None, lenient: bool) -> dict[str, Any]:
    """What ``partial`` and ``lenient`` change about a kernel service spec, which may be nothing."""
    changes: dict[str, Any] = {}
    validator = spec.validator
    if (
        partial is not None
        and validator is not None
        and spec.partial is not partial
        and validator.supports_partial
    ):
        changes["partial"] = partial
    if lenient and isinstance(validator, SerializerValidator) and not validator.lenient:
        changes["validator"] = SerializerValidator(
            validator.serializer,
            serializer_context=validator.serializer_context,
            lenient=True,
            excluded=validator.excluded,
            server_owned=validator.server_owned,
            json_schema_registry=validator.json_schema_registry,
        )
    return changes


__all__ = ["kernel_spec_variant"]
