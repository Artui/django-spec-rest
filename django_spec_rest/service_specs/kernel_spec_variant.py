"""``kernel_spec_variant`` - a kernel spec as one request of the DRF edge dispatches it."""

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
    """``spec`` as one request of the DRF edge dispatches it, derived once per variant.

    With every keyword at its default this is ``kernel_spec(spec)``, the one
    spec every kernel entry point reads. A spec takes two changes, each built
    through its own ``derive`` and so checked as a fresh declaration, and derived
    once per source and held, so a ``Grant`` minted for a variant covers the next
    request's (test_a_grant_for_a_variant_covers_the_next_request_s_variant):

    - ``partial``: the spec with that flag, which the kernel's
      ``relax_partial`` relaxes when it is dispatched; ``None`` reads the spec's
      own. A selector spec has no ``partial``, and a service spec with no
      Validator has nothing a partial call may leave out, which is why the
      kernel refuses ``partial=True`` on one, so a ``PATCH`` runs it whole. A
      Validator that cannot take a partial call (``supports_partial`` false, a
      dataclass's) is validated whole, so the variant is the spec itself.
    - ``lenient``: the spec's ``SerializerValidator`` declared lenient, every
      other keyword of it carried over, so the kernel's shape check passes each
      value through to the serializer. The edge asks this for a request a live
      DRF view dispatches, which DRF's serializer has always answered alone: a
      form's ``"on"`` for a boolean, ``123`` for a string, every field's refusal
      at once, in DRF's words. A caller off HTTP keeps the kernel's typed check.
      A ``many`` spec keeps its ``many_min_length`` and ``many_max_length``: a
      kernel spec declares them itself, so the kernel's cap stays the one its
      author left in place (test_a_lenient_variant_keeps_a_many_spec_s_bounds).
      Any other Validator declares what it takes as it validates it, so has
      nothing to relax.

    A spec neither would change is answered as itself and held by nothing
    (test_a_variant_with_nothing_to_change_is_the_spec_itself).
    """
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
    """A kernel spec's variant: ``partial`` and ``lenient`` derived, and nothing else asked of it.

    The variant is never ``spec`` itself once held, or ``_VARIANTS`` would
    hold the source alive and its weak reference would never fire, so a spec
    neither flag changes returns before anything is held
    (test_a_variant_with_nothing_to_change_is_the_spec_itself asserts it is
    held by nothing).
    """
    partial, lenient = key
    changes = _kernel_changes(spec, partial, lenient) if isinstance(spec, KernelServiceSpec) else {}
    if not changes:
        return spec
    return _held(spec, key, lambda: spec.derive(**changes))


def _kernel_changes(spec: KernelServiceSpec, partial: bool | None, lenient: bool) -> dict[str, Any]:
    """What ``partial`` and ``lenient`` change about a kernel service spec, which may be nothing."""
    changes: dict[str, Any] = {}
    validator = spec.validator
    # One arc to coverage, so each conjunct is named by its case of
    # test_a_variant_with_nothing_to_change_is_the_spec_itself: ``already-lenient``
    # without the first (``None`` reads the spec's own, so derives nothing),
    # ``no-validator`` without the second (the kernel refuses ``partial=True``
    # there), ``already-whole`` / ``already-partial`` without the third, and, for
    # the fourth, test_a_partial_variant_over_a_validator_that_cannot_be_partial_is_the_spec_itself
    # (a Validator that builds every field is validated whole, as drfs validated a
    # ``PATCH`` to a dataclass, where ``derive`` would refuse ``partial=True``).
    if (
        partial is not None
        and validator is not None
        and spec.partial is not partial
        and validator.supports_partial
    ):
        changes["partial"] = partial
    # One arc to coverage, so each conjunct is named: without the first, every
    # partial variant's Validator is relaxed too
    # (test_a_partial_variant_is_derived_and_the_spec_is_untouched holds it is
    # the spec's own); without the second, ``lenient-over-another-validator``
    # of test_a_variant_with_nothing_to_change_is_the_spec_itself raises, a
    # DataclassValidator having no serializer to redeclare; and without the
    # third, its ``already-lenient`` case is derived again.
    if lenient and isinstance(validator, SerializerValidator) and not validator.lenient:
        changes["validator"] = SerializerValidator(
            validator.serializer,
            serializer_context=validator.serializer_context,
            lenient=True,
            # Each carried over, or the variant's call answers otherwise than
            # the spec's on what the edge never asked it to change
            # (test_a_lenient_variant_carries_the_validator_s_other_keywords).
            excluded=validator.excluded,
            server_owned=validator.server_owned,
            json_schema_registry=validator.json_schema_registry,
        )
    return changes


__all__ = ["kernel_spec_variant"]
