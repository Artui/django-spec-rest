from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any, ClassVar, TypeVar

from django.core.exceptions import ImproperlyConfigured
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from rest_framework.exceptions import MethodNotAllowed

from django_spec_rest.types.discriminated_action import DiscriminatedAction
from django_spec_rest.views.mutation.mutation_flow_mixin import MutationFlowMixin
from django_spec_rest.views.mutation.utils import _ServesRaisedSchema
from django_spec_rest.views.spec_options import spec_options
from django_spec_rest.views.spec_validation import (
    _check_kernel_seeds,
    _validate_response_finalizer,
    _validate_success_status,
    refuse_a_stray_variant,
    validate_discriminated_action,
    validate_mutation_view_spec,
    validate_selector_view_spec,
)
from django_spec_rest.views.utils import MountedView, mounted_view, view_pool_seeds
from django_spec_rest.viewsets.warn_unscoped_get_queryset import (
    _overriding_classes,
    warn_unscoped_get_queryset,
)

ActionSpec = KernelServiceSpec | KernelSelectorSpec | DiscriminatedAction

# ``has_instance`` is whether the action acts on one row, so a spec naming no
# target for it is refused.
_MUTATION_ACTIONS: dict[str, dict[str, Any]] = {
    "create": {"has_instance": False},
    "update": {"has_instance": True},
    "partial_update": {"has_instance": True},
    "destroy": {"has_instance": True},
}
_SELECTOR_ACTION_KIND: dict[str, SelectorKind] = {
    "list": SelectorKind.LIST,
    "retrieve": SelectorKind.RETRIEVE,
}

# PATCH and PUT share one spec unless a dedicated ``"partial_update"`` entry
# exists. Must be applied at every resolution site (see
# ``resolve_action_spec_entry``).
_ACTION_SPEC_FALLBACKS: dict[str, str] = {
    "partial_update": "update",
}


def resolve_action_spec_entry(
    action_specs: Mapping[str, ActionSpec],
    action: str | None,
) -> ActionSpec | None:
    """Return the ``action_specs`` entry for ``action``, following fallbacks."""
    if action is None:
        return None
    entry = action_specs.get(action)
    if entry is not None:
        return entry
    fallback = _ACTION_SPEC_FALLBACKS.get(action)
    if fallback is not None:
        return action_specs.get(fallback)
    return None


_HandlerT = TypeVar("_HandlerT", bound=Callable[..., Any])


def dispatches_action_specs(handler: _HandlerT) -> _HandlerT:
    """Mark a viewset handler as this package's own ``action_specs`` dispatcher."""
    handler._dispatches_action_specs = True  # ty: ignore[unresolved-attribute]
    return handler


def resolve_action_spec(view: Any, action: str | None) -> ActionSpec | None:
    """Return the spec ``action`` routes to on ``view``, from either source."""
    spec = resolve_action_spec_entry(view.action_specs, action)
    if spec is not None or action is None:
        return spec
    handler: Any = getattr(view, action, None)
    return getattr(handler, "_service_spec", None) or getattr(handler, "_selector_spec", None)


def resolve_action_service_spec(
    action_specs: Mapping[str, ActionSpec],
    action: str,
    method: str,
) -> KernelServiceSpec | DiscriminatedAction:
    """Pick the kernel ``ServiceSpec`` from ``action_specs`` for a mutation action."""
    entry = resolve_action_spec_entry(action_specs, action)
    if entry is None:
        raise MethodNotAllowed(method)
    if not isinstance(entry, KernelServiceSpec | DiscriminatedAction):
        raise ImproperlyConfigured(
            f"action_specs[{action!r}] must be a ServiceSpec, got "
            f"{type(entry).__name__}. "
            "Use ServiceSpec(service=...) for write actions."
        )
    return entry


def resolve_action_selector_spec(
    action_specs: Mapping[str, ActionSpec],
    action: str,
) -> KernelSelectorSpec | None:
    """Pick the kernel ``SelectorSpec`` from ``action_specs`` for a read action."""
    entry = action_specs.get(action)
    if entry is None:
        return None
    if not isinstance(entry, KernelSelectorSpec):
        raise ImproperlyConfigured(
            f"action_specs[{action!r}] must be a SelectorSpec, got "
            f"{type(entry).__name__}. "
            "Wrap the selector: SelectorSpec(selector=your_callable)."
        )
    return entry


# The view's two HTTP answers, which an action may declare for itself.
_ANSWERS = ("success_status", "response_finalizer")


def _as_the_instance_reads(view_cls: type | MountedView, name: str) -> Any:
    """``name`` on ``view_cls`` as an instance of it reads the attribute, or ``None``."""
    base: Any = view_cls
    while isinstance(base, MountedView):
        overrides: dict[str, Any] = base._mounted_overrides
        if name in overrides:
            return overrides[name]
        base = base._mounted_base
    raw = inspect.getattr_static(base, name, None)
    get = getattr(type(raw), "__get__", None)
    return raw if get is None else get(raw, view_cls, base)


def _action_hooks(view_cls: type | MountedView, action: str) -> dict[str, Any]:
    """Each ``get_<action>_<answer>`` hook ``view_cls`` defines, as an instance reads it."""
    hooks: dict[str, Any] = {}
    for name in _ANSWERS:
        hook_name = f"get_{action}_{name}"
        hook = _as_the_instance_reads(view_cls, hook_name)
        if hook is None:
            continue
        if callable(hook):
            try:
                inspect.signature(hook)
            except ValueError as error:
                raise ImproperlyConfigured(
                    f"{view_cls.__name__}: {hook_name} is read as a method, so its first "
                    "parameter is the view, and it declares none. Declare `self`, or wrap "
                    "a plain function in staticmethod()."
                ) from error
        hooks[name] = hook
    return hooks


def _as_mounted(
    view_cls: type | MountedView, action: str, spec: object, *, label: str
) -> MountedView:
    """``view_cls`` as a standalone view would carry ``spec``: on ``spec``, serving ``action``."""
    overrides = {"spec": spec, "action": action, **_action_hooks(view_cls, action)}
    return MountedView(view_cls, overrides, name=label)


def _validate_kernel_action_spec(
    view_cls: type | MountedView,
    action: str,
    spec: KernelServiceSpec | KernelSelectorSpec,
    *,
    label: str,
    pool_seeds: PoolSeeds,
    discriminated: bool = False,
) -> None:
    """Ask a kernel entry the checks a standalone view asks of its kernel ``spec``."""
    mounted = _as_mounted(view_cls, action, spec, label=label)
    if action in _MUTATION_ACTIONS:
        validate_mutation_view_spec(
            mounted,
            has_instance=_MUTATION_ACTIONS[action]["has_instance"],
            pool_seeds=pool_seeds,
            discriminated=discriminated,
        )
    elif action in _SELECTOR_ACTION_KIND:
        validate_selector_view_spec(
            mounted,
            expected_kind=_SELECTOR_ACTION_KIND[action],
            pool_seeds=pool_seeds,
        )
    else:
        raise ImproperlyConfigured(
            f"{label} is a kernel {type(spec).__name__} under a key no action of the "
            "viewset dispatches, so its permissions would guard nothing. Serve it with "
            "@service_action(spec) or @selector_action(spec) on the action's method."
        )


def _validate_action_spec(
    view_cls: type | MountedView, action: str, spec: object, *, pool_seeds: PoolSeeds
) -> None:
    """Run fail-fast validation for a single ``action_specs`` entry."""
    label = f"{view_cls.__name__}.action_specs[{action!r}]"
    if isinstance(spec, DiscriminatedAction):
        _validate_discriminated_entry(view_cls, action, spec, label=label, pool_seeds=pool_seeds)
        return
    if not isinstance(spec, KernelServiceSpec | KernelSelectorSpec):
        raise ImproperlyConfigured(
            f"{label} must be a ServiceSpec or SelectorSpec, got {type(spec).__name__}."
        )
    _validate_kernel_action_spec(view_cls, action, spec, label=label, pool_seeds=pool_seeds)


def _validate_discriminated_entry(
    view_cls: type | MountedView,
    action: str,
    entry: DiscriminatedAction,
    *,
    label: str,
    pool_seeds: PoolSeeds,
) -> None:
    """Ask a ``DiscriminatedAction`` entry its own shape, then each variant as a plain entry."""
    if action not in _MUTATION_ACTIONS:
        raise ImproperlyConfigured(
            f"{label} is a DiscriminatedAction, which serves a write action. Put it under "
            "create, update, partial_update or destroy, or hand it to @service_action on the "
            "action's method."
        )
    validate_discriminated_action(entry, label=label)
    for key, variant in entry.specs.items():
        _validate_kernel_action_spec(
            view_cls,
            action,
            variant,
            label=f"{label}[{key!r}]",
            pool_seeds=pool_seeds,
            discriminated=True,
        )


def _is_decorated(member: object) -> bool:
    """Whether ``member`` is a handler ``@service_action`` or ``@selector_action`` stamped."""
    return hasattr(member, "_service_spec") or hasattr(member, "_selector_spec")


def _fills_service_keywords(view_cls: type | MountedView, action: str) -> bool:
    """Whether ``view_cls`` has a service-kwargs hook that reaches ``action``'s service."""
    base = MutationFlowMixin.get_service_kwargs
    return getattr(view_cls, "get_service_kwargs", base) is not base or hasattr(
        view_cls, f"get_{action}_service_kwargs"
    )


def _validate_action_answers(
    view_cls: type | MountedView, action: str, handler: Any = None, *, discriminated: bool = False
) -> None:
    """Ask a decorated action's per-action hooks what a standalone view's answers are asked."""
    label = f"{view_cls.__name__}.{action}"
    hooks = _action_hooks(view_cls, action)
    for name in hooks:
        if getattr(handler, f"_{name}", None) is not None:
            raise ImproperlyConfigured(
                f"{label}: @service_action declares `{name}` and the viewset defines "
                f"get_{action}_{name}, so the action has two. Keep one."
            )
    _validate_success_status(hooks.get("success_status"), label=label, discriminated=discriminated)
    _validate_response_finalizer(
        hooks.get("response_finalizer"), label=label, discriminated=discriminated
    )


def _refuse_view_answers_naming_variant(
    view_cls: type | MountedView, action: str, handler: Any
) -> None:
    """Refuse the view's own answers declaring ``variant``, for a plain decorated service action."""
    hooks = _action_hooks(view_cls, action)
    for name in _ANSWERS:
        if name not in hooks and getattr(handler, f"_{name}", None) is None:
            refuse_a_stray_variant(
                getattr(view_cls, name, None), label=f"{view_cls.__name__}.{action}", seat=name
            )


def _each_kernel_spec(
    action: str, spec: ActionSpec
) -> list[tuple[str, KernelServiceSpec | KernelSelectorSpec]]:
    """The kernel specs ``spec`` serves ``action`` with, each with the name a refusal gives it."""
    if isinstance(spec, DiscriminatedAction):
        return [(f"{action}[{key!r}]", variant) for key, variant in spec.specs.items()]
    return [(action, spec)]


def _validate_decorated_actions(view_cls: type | MountedView, *, pool_seeds: PoolSeeds) -> None:
    """Ask each decorated action's spec the kernel's ``check_seeds`` against ``pool_seeds``."""
    for action, handler in inspect.getmembers(view_cls, _is_decorated):
        spec: ActionSpec | None = getattr(handler, "_service_spec", None)
        discriminated = isinstance(spec, DiscriminatedAction)
        _validate_action_answers(view_cls, action, handler, discriminated=discriminated)
        if isinstance(spec, KernelServiceSpec):
            _refuse_view_answers_naming_variant(view_cls, action, handler)
        if spec is not None and _fills_service_keywords(view_cls, action):
            continue
        for label, each in _each_kernel_spec(action, spec or handler._selector_spec):
            try:
                _check_kernel_seeds(each, pool_seeds=pool_seeds)
            except ImproperlyConfigured as refusal:
                raise ImproperlyConfigured(f"{view_cls.__name__}.{label}: {refusal}") from refusal


def _lookup_capture(view_cls: MountedView) -> str:
    """The name a DRF router captures a detail route's lookup under."""
    return getattr(view_cls, "lookup_url_kwarg", None) or getattr(view_cls, "lookup_field", "pk")


def _mapped_specs(
    view_cls: MountedView, actions: Mapping[str, str]
) -> list[tuple[str, KernelServiceSpec | KernelSelectorSpec]]:
    """Each action ``actions`` maps a method to, and each kernel spec serving it, where one does."""
    specs: list[tuple[str, KernelServiceSpec | KernelSelectorSpec]] = []
    for action in dict.fromkeys(actions.values()):
        handler: Any = getattr(view_cls, action, None)
        if _is_decorated(handler):
            spec = getattr(handler, "_service_spec", None) or handler._selector_spec
        else:
            spec = resolve_action_spec_entry(view_cls.action_specs, action)
        if spec is not None:
            specs.extend(_each_kernel_spec(action, spec))
    return specs


def _row_lookup(spec: KernelServiceSpec | KernelSelectorSpec) -> KernelSelectorSpec | None:
    """The selector that finds the one row ``spec`` acts on, or ``None`` where it finds none."""
    if isinstance(spec, KernelSelectorSpec):
        return spec
    return spec.instance_selector_spec


def _validate_lookup_captures(
    view_cls: MountedView, actions: Mapping[str, str] | None, initkwargs: Mapping[str, Any]
) -> None:
    """Refuse a detail route whose row lookup declares no parameter for the router's capture."""
    if initkwargs.get("detail") is not True or not actions:
        return
    capture = _lookup_capture(view_cls)
    for action, spec in _mapped_specs(view_cls, actions):
        lookup = _row_lookup(spec)
        if lookup is not None and lookup.parameters().get(capture) is None:
            raise ImproperlyConfigured(
                f"{view_cls.__name__}.{action}: the router captures the lookup as "
                f"{capture!r} (lookup_url_kwarg, else lookup_field), and the selector "
                "finding the row declares no parameter of that name, so the capture "
                "never reaches it. Declare it on that selector: "
                f'reads=Parameters.of(Parameter("{capture}", ..., required=True)), '
                "or set lookup_url_kwarg to the name it reads."
            )


# Each read handler that falls back to DRF, and what of a project's own takes that read over.
_READ_HANDLERS = {"list": ("list",), "retrieve": ("retrieve", "get_object")}


def _defined_by_the_project(view_cls: type, *names: str) -> bool:
    """Whether any class above ``view_cls`` but this package's or DRF's defines one of ``names``."""
    return any(_overriding_classes(view_cls, name) for name in names)


class _ActionSpecsMixin(_ServesRaisedSchema):
    """Declares the ``action_specs`` class attribute shared by all viewset mixins.

    All per-action mixins and
    [`ActionSerializerResolver`][django_spec_rest.viewsets.action_serializer_resolver.ActionSerializerResolver]
    inherit from this so the attribute is defined in exactly one place. ``as_view`` runs
    fail-fast spec validation once per view at URL-wiring time: of every
    ``action_specs`` entry, and the seed check of every ``@service_action`` and
    ``@selector_action`` spec, against the viewset's ``pool_seeds``. A decorated
    action on DRF's own ``GenericViewSet`` or ``ViewSet``, with no base of this
    package's, has no such ``as_view``, so its seeds are its first request's.

    A kernel spec declares no ``permission_classes``: its checks are its
    ``permissions``, which the kernel's ``dispatch`` asks after DRF has asked the
    view's own (test_service_viewset's
    test_the_view_s_own_classes_refuse_before_the_spec_runs).
    """

    action_specs: ClassVar[Mapping[str, ActionSpec]] = {}

    lenient_json_body: bool | None = None
    """Whether this viewset's serializers alone answer a JSON body; see
    [`MutationFlowMixin`][django_spec_rest.views.mutation.mutation_flow_mixin.MutationFlowMixin].
    Declared here too so a ``@service_action`` may name it on any of the
    viewset bases (test_a_service_action_may_declare_its_own)."""

    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS
    """The seeds the spec's callables are resolved with: the kernel's
    ``DEFAULT_POOL_SEEDS`` unless the view registers others, as a class
    attribute or as ``as_view(pool_seeds=...)``. One registry for the view's
    life: ``as_view()`` checks the spec against it, refusing a callable that
    requires a seed it does not register, and every call's checks, target
    lookup and ``dispatch`` are handed that object (test_pool_seeds)."""

    action: str | None
    action_map: dict[str, str]
    kwargs: dict[str, Any]
    request: Any

    @classmethod
    def as_view(cls, *args: Any, **initkwargs: Any) -> Any:
        # Checked as instances will be, keywords included (``mounted_view``).
        mounted = mounted_view(cls, initkwargs)
        pool_seeds = view_pool_seeds(mounted)
        for action, spec in mounted.action_specs.items():
            _validate_action_spec(mounted, action, spec, pool_seeds=pool_seeds)
        for action, fallback in _ACTION_SPEC_FALLBACKS.items():
            if fallback in mounted.action_specs:
                entry = resolve_action_spec_entry(mounted.action_specs, action)
                _validate_action_answers(
                    mounted, action, discriminated=isinstance(entry, DiscriminatedAction)
                )
        _validate_decorated_actions(mounted, pool_seeds=pool_seeds)
        actions = args[0] if args else initkwargs.get("actions")
        _validate_lookup_captures(mounted, actions, initkwargs)
        warn_unscoped_get_queryset(mounted)
        return super().as_view(*args, **initkwargs)  # ty: ignore[unresolved-attribute]

    def options(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        """Answer OPTIONS from the kernel specs the route serves, or as DRF does."""
        served = self._kernel_specs_served()
        if served:
            return spec_options(self, request, served)
        try:
            return super().options(request, *args, **kwargs)  # ty: ignore[unresolved-attribute]
        except AssertionError:
            return spec_options(self, request, served)

    def _kernel_specs_served(self) -> dict[str, ActionSpec]:
        """Each method the route maps to an action served by a kernel spec, and that spec."""
        served: dict[str, ActionSpec] = {}
        for method, action in getattr(self, "action_map", {}).items():
            spec = resolve_action_spec(self, action)
            if spec is not None:
                served[method.upper()] = spec
        return served

    @property
    def allowed_methods(self) -> list[str]:
        """DRF's, less a method this package's own handler would refuse."""
        methods: list[str] = super().allowed_methods  # ty: ignore[unresolved-attribute]
        return [method for method in methods if not self._refuses_without_a_spec(method)]

    def _refuses_without_a_spec(self, method: str) -> bool:
        """Whether ``method`` is left out of ``Allow``: one rule, read by the schema too."""
        return self._refuses(method.lower()) and (
            bool(self._kernel_specs_served()) or self._fallback_cannot_run()
        )

    def _refuses(self, method: str) -> bool:
        """Whether ``method`` reaches one of this package's handlers with nothing to serve it."""
        action = getattr(self, "action_map", {}).get(method, "")
        marked = getattr(getattr(self, action, None), "_dispatches_action_specs", False)
        unserved = marked and resolve_action_spec(self, action) is None
        return unserved or self._has_no_fallback(action)

    def _has_no_fallback(self, action: str) -> bool:
        """Whether a read has no spec, no project handler, and a fallback that cannot run."""
        return (
            action in _READ_HANDLERS
            and resolve_action_spec(self, action) is None
            and not _defined_by_the_project(type(self), *_READ_HANDLERS[action])
            and self._fallback_cannot_run()
        )

    def _fallback_cannot_run(self) -> bool:
        """Whether DRF's reads lack rows or a serializer, so could only raise their assertion."""
        view_cls = type(self)
        has_rows = getattr(self, "queryset", None) is not None or _defined_by_the_project(
            view_cls, "get_queryset"
        )
        has_serializer = getattr(self, "serializer_class", None) is not None or (
            _defined_by_the_project(view_cls, "get_serializer_class", "get_serializer")
        )
        return not has_rows or not has_serializer
