from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django_service_specs.dispatch.check_seeds import check_seeds
from django_service_specs.pool.pool_seeds import PoolSeeds
from django_service_specs.schema.file_output import file_output
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from django_service_specs.types.is_async import is_async
from django_service_specs.types.selector_kind import SelectorKind

from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.types.discriminated_action import DiscriminatedAction
from django_spec_rest.views.utils import MountedView


def _required_kw_params(fn: Callable[..., Any]) -> dict[str, inspect.Parameter]:
    """Return the kw-resolvable params of ``fn`` with no default, keyed by name."""
    sig = inspect.signature(fn)
    return {
        name: p
        for name, p in sig.parameters.items()
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        and p.default is inspect.Parameter.empty
    }


def _positional_only(fn: Callable[..., Any]) -> list[str]:
    """The ``fn`` parameters taking a value by position alone, with no default, sorted."""
    return sorted(
        name
        for name, p in inspect.signature(fn).parameters.items()
        if p.kind is inspect.Parameter.POSITIONAL_ONLY and p.default is inspect.Parameter.empty
    )


def _refuse_positional_only(fn: Callable[..., Any], *, label: str, seat: str) -> None:
    """``ImproperlyConfigured`` where ``fn`` takes a parameter ``_positional_only`` names."""
    positional = _positional_only(fn)
    if positional:
        raise ImproperlyConfigured(
            f"{label}: `{seat}` takes parameter(s) {positional} by position only, which the "
            "framework never supplies: it hands every value by keyword. Declare them as "
            "keyword parameters, or give each a default."
        )


def is_overridden(view_cls: type | MountedView, base_cls: type, method_name: str) -> bool:
    """Return ``True`` if ``view_cls`` overrides ``base_cls``'s ``method_name``."""
    base = getattr(base_cls, method_name, None)
    if base is None:
        return hasattr(view_cls, method_name)
    return getattr(view_cls, method_name, None) is not base


def _uses_django_filter_backend(view_cls: type | MountedView) -> bool:
    """True when ``view_cls.filter_backends`` includes a ``DjangoFilterBackend``."""
    backends = getattr(view_cls, "filter_backends", None) or ()
    return any(
        any(
            getattr(klass, "__name__", "") == "DjangoFilterBackend"
            for klass in getattr(backend, "__mro__", ())
        )
        for backend in backends
    )


def validate_filter_set_no_backend_conflict(
    view_cls: type | MountedView,
    spec: KernelSelectorSpec,
    *,
    label: str,
) -> None:
    """Reject a list selector that sets ``filter_set`` *and* wires ``DjangoFilterBackend``."""
    if spec.filter_set is None or not _uses_django_filter_backend(view_cls):
        return
    raise ImproperlyConfigured(
        f"{label}: spec.filter_set is set and the view's filter_backends "
        "includes DjangoFilterBackend. `filter_set` replaces "
        "DjangoFilterBackend (both apply a FilterSet to the list queryset), so "
        "the queryset would be filtered twice. Drop DjangoFilterBackend from "
        "filter_backends for this action, or remove filter_set from the spec."
    )


# Keys the status pool offers a ``success_status`` callable.
_SUCCESS_STATUS_KEYS = frozenset({"result", "instance", "request", "view"})

# Keys the framework offers a ``response_finalizer`` callable.
_RESPONSE_FINALIZER_KEYS = frozenset({"response", "result", "request", "view", "instance", "data"})

# The chosen key, which both offer on a discriminated action and nowhere else.
_VARIANT = "variant"

# Keys the dispatching handler offers a ``DiscriminatedAction``'s discriminator.
_DISCRIMINATOR_KEYS = frozenset({"request", "data", "user", "view", "call_context"})

_KEYWORD_KINDS = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)


def refuse_a_stray_variant(answer: Any, *, label: str, seat: str) -> None:
    """Refuse a callable answer naming ``variant`` where no discriminated action offers it."""
    declared = inspect.signature(answer).parameters.get(_VARIANT) if callable(answer) else None
    if declared is not None and declared.kind in _KEYWORD_KINDS:
        raise ImproperlyConfigured(
            f"{label}: `{seat}` declares `{_VARIANT}`, the key a DiscriminatedAction chose, and "
            "this action is not discriminated, so nothing would ever hand it. Remove it, or "
            "declare it on the action's own answer."
        )


def _validate_success_status(
    success_status: int | Callable[..., int] | None, *, label: str, discriminated: bool = False
) -> None:
    """Reject a ``success_status`` that is neither int/None nor a well-formed callable."""
    if success_status is None or isinstance(success_status, int):
        return
    if not callable(success_status):
        raise ImproperlyConfigured(
            f"{label}: `success_status` must be an int, a callable returning an int, "
            f"or None — got {type(success_status).__name__}."
        )
    _refuse_positional_only(success_status, label=label, seat="success_status")
    if not discriminated:
        refuse_a_stray_variant(success_status, label=label, seat="success_status")
    keys = _SUCCESS_STATUS_KEYS | {_VARIANT} if discriminated else _SUCCESS_STATUS_KEYS
    unknown = set(_required_kw_params(success_status)) - keys
    if unknown:
        raise ImproperlyConfigured(
            f"{label}: `success_status` callable requires parameter(s) "
            f"{sorted(unknown)} the framework can't supply — declare only a subset "
            f"of {sorted(keys)}, and `**kwargs` for the rest."
        )


def _validate_response_finalizer(
    finalizer: Any, *, label: str, discriminated: bool = False
) -> None:
    """Reject a ``response_finalizer`` that isn't a well-formed callable."""
    if finalizer is None:
        return
    if not callable(finalizer):
        raise ImproperlyConfigured(
            f"{label}: `response_finalizer` must be a callable returning a Response "
            f"or None — got {type(finalizer).__name__}."
        )
    _refuse_positional_only(finalizer, label=label, seat="response_finalizer")
    if not discriminated:
        refuse_a_stray_variant(finalizer, label=label, seat="response_finalizer")
    keys = _RESPONSE_FINALIZER_KEYS | {_VARIANT} if discriminated else _RESPONSE_FINALIZER_KEYS
    unknown = set(_required_kw_params(finalizer)) - keys
    if unknown:
        raise ImproperlyConfigured(
            f"{label}: `response_finalizer` requires parameter(s) {sorted(unknown)} the "
            f"framework can't supply — declare only a subset of "
            f"{sorted(keys)}, and `**kwargs` for the rest."
        )


def validate_discriminated_action(action: DiscriminatedAction, *, label: str) -> None:
    """Refuse the shape of a ``DiscriminatedAction`` no request could be served through."""
    specs: Any = action.specs
    if not isinstance(specs, Mapping) or not specs:
        raise ImproperlyConfigured(
            f"{label}: a DiscriminatedAction must map each key to a ServiceSpec, and has no "
            "variants to choose from."
        )
    strays = [key for key in specs if not isinstance(key, str)]
    if strays:
        raise ImproperlyConfigured(
            f"{label}: a DiscriminatedAction's keys are strings, and these are not: {strays}."
        )
    for key, variant in specs.items():
        if variant is None:
            raise ImproperlyConfigured(
                f"{label}[{key!r}]: a DiscriminatedAction's variants are ServiceSpecs, and this "
                "is None."
            )
    discriminator: Any = action.discriminator
    if not callable(discriminator):
        raise ImproperlyConfigured(
            f"{label}: `discriminator` must be a callable answering one of {sorted(specs)}, got "
            f"{type(discriminator).__name__}."
        )
    if is_async(discriminator):
        raise ImproperlyConfigured(
            f"{label}: `discriminator` is async, and nothing on this route awaits it. Declare "
            "it with `def`."
        )
    _refuse_positional_only(discriminator, label=label, seat="discriminator")
    named = {
        name
        for name, parameter in inspect.signature(discriminator).parameters.items()
        if parameter.kind in _KEYWORD_KINDS
    }
    unknown = named - _DISCRIMINATOR_KEYS
    if unknown:
        raise ImproperlyConfigured(
            f"{label}: `discriminator` declares parameter(s) {sorted(unknown)} the framework "
            f"can't supply — declare only a subset of {sorted(_DISCRIMINATOR_KEYS)}, and "
            "`**kwargs` for the rest."
        )


def _validate_selector_kind(
    spec: KernelSelectorSpec,
    *,
    label: str,
    expected_kind: SelectorKind,
) -> None:
    """Reject a spec whose ``kind`` is not the one its mount point is shaped for."""
    if spec.kind is not expected_kind:
        raise ImproperlyConfigured(
            f"{label}: spec.kind is {spec.kind!r} but this mount point "
            f"expects {expected_kind!r}. Construct the spec with "
            f"kind={expected_kind!r} or move it to the matching view."
        )


def _serves_the_other_kind(view_cls: type | MountedView, spec: Any, served: type) -> str:
    """Why ``view_cls`` refuses ``spec``: a kernel spec of the kind the view does not serve."""
    if isinstance(spec, DiscriminatedAction):
        return (
            f"{view_cls.__name__}.spec is a DiscriminatedAction, which one action of a viewset "
            "dispatches. Put it in action_specs under create, update, partial_update or "
            "destroy, or hand it to @service_action."
        )
    return (
        f"{view_cls.__name__}.spec is a {type(spec).__name__}, but this view serves a "
        f"{served.__name__}. Set the spec on a view of its own kind."
    )


def _check_kernel_seeds(
    spec: KernelServiceSpec | KernelSelectorSpec, *, pool_seeds: PoolSeeds
) -> None:
    """Refuse at ``as_view()`` what the kernel's ``check_seeds`` refuses of ``spec``."""
    validator = spec.validator if isinstance(spec, KernelServiceSpec) else None
    if isinstance(validator, SerializerValidator):
        try:
            validator.parameters()
        except (AttributeError, KeyError):
            return
    check_seeds(spec, pool_seeds=pool_seeds)


def validate_mutation_view_spec(
    view_cls: type | MountedView,
    *,
    has_instance: bool,
    pool_seeds: PoolSeeds,
    discriminated: bool = False,
) -> None:
    """Validate ``view_cls.spec`` on a standalone mutation view."""
    spec: KernelServiceSpec | KernelSelectorSpec | None = getattr(view_cls, "spec", None)
    if spec is None:
        return
    if not isinstance(spec, KernelServiceSpec):
        raise ImproperlyConfigured(_serves_the_other_kind(view_cls, spec, KernelServiceSpec))
    from django_spec_rest.views.mutation.mutation_flow_mixin import (
        MutationFlowMixin,
    )

    hooked = is_overridden(view_cls, MutationFlowMixin, "get_service_kwargs")
    _validate_success_status(
        getattr(view_cls, "success_status", None),
        label=view_cls.__name__,
        discriminated=discriminated,
    )
    _validate_response_finalizer(
        getattr(view_cls, "response_finalizer", None),
        label=view_cls.__name__,
        discriminated=discriminated,
    )
    _refuse_a_detail_spec_with_no_target(view_cls, spec, has_instance=has_instance)
    _refuse_a_file_of_many(view_cls, spec)
    if not (hooked or _overrides_the_action_hook(view_cls, "service")):
        try:
            _check_kernel_seeds(spec, pool_seeds=pool_seeds)
        except ImproperlyConfigured as refusal:
            if not discriminated:
                raise
            raise ImproperlyConfigured(f"{view_cls.__name__}: {refusal}") from refusal


def _refuse_a_detail_spec_with_no_target(
    view_cls: type | MountedView, spec: KernelServiceSpec, *, has_instance: bool
) -> None:
    """Refuse an update or delete view's kernel spec that names nothing for it to act on."""
    if has_instance and not spec.many and spec.target_selector_spec() is None:
        raise ImproperlyConfigured(
            f"{view_cls.__name__}.spec declares no target selector, so it would act on no "
            "row: a kernel spec's target is its own lookup's, and the view's get_object() is "
            "never asked for one. Set instance_selector_spec to the row it acts on, "
            "collection_selector_spec to a set, or many=True for a list body."
        )


def _refuse_a_file_of_many(
    view_cls: type | MountedView, spec: KernelServiceSpec | KernelSelectorSpec
) -> None:
    """Refuse, naming the view, a file the kernel's ``file_output`` says has no answer."""
    try:
        file_output(spec)
    except ImproperlyConfigured as refusal:
        raise ImproperlyConfigured(f"{view_cls.__name__}: {refusal}") from refusal


def _refuse_selector_hooks(view_cls: type | MountedView) -> None:
    """Refuse a selector view's ``get_selector_kwargs`` hooks beside a kernel spec."""
    action = getattr(view_cls, "action", None)
    for hook, overridden in (
        ("get_selector_kwargs", hasattr(view_cls, "get_selector_kwargs")),
        (f"get_{action}_selector_kwargs", _overrides_the_action_hook(view_cls, "selector")),
    ):
        if overridden:
            raise ImproperlyConfigured(
                f"{view_cls.__name__} overrides {hook}, which never reaches a kernel spec: "
                "its keywords are its own providers'. Return those keys from the spec's "
                "kwargs provider (SelectorSpec(kwargs=...)), which may declare the request "
                "and the view."
            )


def _overrides_the_action_hook(view_cls: type | MountedView, chain: str) -> bool:
    """Whether ``view_cls`` defines ``get_<action>_<chain>_kwargs`` for the ``action`` it sets."""
    action = getattr(view_cls, "action", None)
    return isinstance(action, str) and hasattr(view_cls, f"get_{action}_{chain}_kwargs")


def validate_selector_view_spec(
    view_cls: type | MountedView,
    *,
    expected_kind: SelectorKind,
    pool_seeds: PoolSeeds,
) -> None:
    """Validate ``view_cls.spec`` on a standalone selector view."""
    spec: KernelSelectorSpec | KernelServiceSpec | None = getattr(view_cls, "spec", None)
    if spec is None:
        return
    label = f"{view_cls.__name__}.spec"
    if not isinstance(spec, KernelSelectorSpec):
        raise ImproperlyConfigured(_serves_the_other_kind(view_cls, spec, KernelSelectorSpec))
    _validate_selector_kind(spec, label=label, expected_kind=expected_kind)
    _refuse_a_file_of_many(view_cls, spec)
    _refuse_selector_hooks(view_cls)
    _check_kernel_seeds(spec, pool_seeds=pool_seeds)
    if expected_kind is SelectorKind.LIST:
        validate_filter_set_no_backend_conflict(view_cls, spec, label=label)
