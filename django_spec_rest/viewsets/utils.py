"""Shared infrastructure for viewset mixins."""

from __future__ import annotations

import inspect
import types
from collections.abc import Callable, Mapping
from typing import Any, ClassVar, TypeVar

from django.core.exceptions import ImproperlyConfigured
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from rest_framework.exceptions import MethodNotAllowed

from django_spec_rest.views.mutation.mutation_flow_mixin import MutationFlowMixin
from django_spec_rest.views.mutation.utils import _ServesRaisedSchema
from django_spec_rest.views.spec_options import spec_options
from django_spec_rest.views.spec_validation import (
    _check_kernel_seeds,
    _validate_response_finalizer,
    _validate_success_status,
    validate_mutation_view_spec,
    validate_selector_view_spec,
)
from django_spec_rest.views.utils import MountedView, mounted_view, view_pool_seeds

ActionSpec = KernelServiceSpec | KernelSelectorSpec

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
    """Return the ``action_specs`` entry for ``action``, following fallbacks.

    Single source of truth for the action→spec-key chain: dispatch, permission
    resolution and serializer resolution must all route through here, or they
    disagree on the key (an ``"update"``-keyed spec's ``permission_classes``
    silently not applying under PATCH).
    """
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
    """Mark a viewset handler as this package's own ``action_specs`` dispatcher.

    Such a handler answers 405 when no spec serves its action, so ``Allow`` and
    OPTIONS leave that method out rather than describe a body nobody accepts. A
    handler the view defines itself, even one calling ``super()``, is not
    marked: what it accepts is its own business, and OPTIONS describes it as
    DRF always has.
    """
    handler._dispatches_action_specs = True  # ty: ignore[unresolved-attribute]
    return handler


def resolve_action_spec(view: Any, action: str | None) -> ActionSpec | None:
    """Return the spec ``action`` routes to on ``view``, from either source.

    A spec reaches a viewset two ways: keyed in ``action_specs`` (read through
    [`resolve_action_spec_entry`][django_spec_rest.viewsets.utils.resolve_action_spec_entry],
    fallbacks included), or stamped on the bound handler by ``@service_action`` /
    ``@selector_action``. ``get_permissions`` and the OPTIONS metadata path both
    ask through here, so a hook that reads only one of the two cannot be written
    by accident again: it is how OPTIONS on a ``@service_action`` POST came to
    500 while its permissions resolved fine.

    ``action`` is taken as given and never translated. DRF's implicit
    ``"metadata"`` action has no handler and no entry, so it resolves to
    ``None``; the metadata path names the action it describes itself.

    The ``getattr`` default is load-bearing: no handler exists for an implicit
    action, and an ``AttributeError`` is not an ``APIException``, so
    ``handle_exception`` would re-raise it and every OPTIONS request (CORS
    preflights included) would 500 before permissions are evaluated. So is the
    ``action is None`` check, for a method the action map does not route: held
    by the ``None`` case of test_a_kernel_entry_resolves_to_the_view_s_serializer_class.
    """
    spec = resolve_action_spec_entry(view.action_specs, action)
    if spec is not None or action is None:
        return spec
    handler: Any = getattr(view, action, None)
    return getattr(handler, "_service_spec", None) or getattr(handler, "_selector_spec", None)


def resolve_action_service_spec(
    action_specs: Mapping[str, ActionSpec],
    action: str,
    method: str,
) -> KernelServiceSpec:
    """Pick the kernel ``ServiceSpec`` from ``action_specs`` for a mutation action.

    Centralised so all three mutation viewset mixins share one error path."""
    entry = resolve_action_spec_entry(action_specs, action)
    if entry is None:
        raise MethodNotAllowed(method)
    # ``as_view`` refuses this pairing at setup, so reaching it means the mapping
    # was built or swapped after the view was wired. Kept as the backstop.
    if not isinstance(entry, KernelServiceSpec):
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
    """Pick the kernel ``SelectorSpec`` from ``action_specs`` for a read action.

    ``None`` means the caller must fall back to vanilla DRF
    (``super().get_queryset()`` / ``super().get_object()``): the action is
    unconfigured. A kernel ``SelectorSpec`` always declares its selector, so an
    entry is never ``None`` for lacking one.
    """
    entry = action_specs.get(action)
    if entry is None:
        return None
    # As above: setup already refused this pairing, so this is the backstop for
    # a mapping that changed afterwards.
    if not isinstance(entry, KernelSelectorSpec):
        raise ImproperlyConfigured(
            f"action_specs[{action!r}] must be a SelectorSpec, got "
            f"{type(entry).__name__}. "
            "Wrap the selector: SelectorSpec(selector=your_callable)."
        )
    return entry


# The view's two HTTP answers, which an action may declare for itself.
_ANSWERS = ("success_status", "response_finalizer")


def _action_hooks(view_cls: type | MountedView, action: str) -> dict[str, Any]:
    """Each ``get_<action>_<answer>`` hook ``view_cls`` defines, as an instance reads it.

    Read off the class a method is unbound, so it is bound here: its ``self``
    is the view, never a key it asks the framework for
    (test_per_action_answers' test_a_hook_s_own_self_is_not_a_key_it_requires).
    An ``int`` is the status as it stands.
    """
    hooks: dict[str, Any] = {}
    for name in _ANSWERS:
        hook = getattr(view_cls, f"get_{action}_{name}", None)
        if hook is not None:
            hooks[name] = types.MethodType(hook, view_cls) if inspect.isfunction(hook) else hook
    return hooks


def _as_mounted(
    view_cls: type | MountedView, action: str, spec: object, *, label: str
) -> MountedView:
    """``view_cls`` as a standalone view would carry ``spec``: on ``spec``, serving ``action``.

    The standalone views' kernel checks (``validate_mutation_view_spec`` and
    ``validate_selector_view_spec``) read the spec, the view's hooks, its
    ``success_status`` and ``response_finalizer`` and the ``action`` its
    per-action hooks are named for, all off the class. The viewset read
    through the entry as its ``spec`` and the key as its ``action`` answers
    each of those as the viewset does for that action, so the entry is asked
    exactly what the standalone view asks of its spec, the checks added to
    those entry points included, rather than a copy of them. A ``MountedView``
    rather than a subclass, so no class is made per entry
    (test_mounting_makes_no_class), and named after the entry, so a refusal
    names the action it is about (test_service_viewset's
    test_the_refusal_names_the_action). The action's own
    ``get_<action>_success_status`` and ``get_<action>_response_finalizer``
    stand in for the viewset's, as they do at dispatch (``action_answer``), so
    the checks ask the value the action answers with
    (test_per_action_answers' TestTheMountedChecksReadThePerActionValue).
    """
    overrides = {"spec": spec, "action": action, **_action_hooks(view_cls, action)}
    return MountedView(view_cls, overrides, name=label)


def _validate_kernel_action_spec(
    view_cls: type | MountedView,
    action: str,
    spec: KernelServiceSpec | KernelSelectorSpec,
    *,
    label: str,
    pool_seeds: PoolSeeds,
) -> None:
    """Ask a kernel entry the checks a standalone view asks of its kernel ``spec``.

    A built-in write action is asked as the matching mutation view is
    (``has_instance`` for an update or a delete, so a spec naming no target is
    refused), and a read action as the matching selector view is, the
    ``kind`` included. A kernel spec under the other kind of action is refused
    by those same checks, against ``pool_seeds``, the viewset's registry.

    **A custom key is refused.** Such an entry feeds ``get_permissions`` and
    the serializer resolver alone, while a kernel spec declares no
    ``permission_classes`` and its own checks are asked by ``dispatch``, which
    a custom key never reaches: the entry would guard nothing it seems to.
    ``@service_action`` and ``@selector_action`` serve one
    (test_service_viewset's test_a_kernel_spec_under_a_custom_key_is_refused).
    """
    mounted = _as_mounted(view_cls, action, spec, label=label)
    if action in _MUTATION_ACTIONS:
        validate_mutation_view_spec(
            mounted,
            has_instance=_MUTATION_ACTIONS[action]["has_instance"],
            pool_seeds=pool_seeds,
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
    """Run fail-fast validation for a single ``action_specs`` entry.

    Every entry is validated, whatever it is keyed on, against the registry
    the viewset dispatches with.
    """
    label = f"{view_cls.__name__}.action_specs[{action!r}]"
    if not isinstance(spec, KernelServiceSpec | KernelSelectorSpec):
        raise ImproperlyConfigured(
            f"{label} must be a ServiceSpec or SelectorSpec, got {type(spec).__name__}."
        )
    _validate_kernel_action_spec(view_cls, action, spec, label=label, pool_seeds=pool_seeds)


def _is_decorated(member: object) -> bool:
    """Whether ``member`` is a handler ``@service_action`` or ``@selector_action`` stamped."""
    return hasattr(member, "_service_spec") or hasattr(member, "_selector_spec")


def _fills_service_keywords(view_cls: type | MountedView, action: str) -> bool:
    """Whether ``view_cls`` has a service-kwargs hook that reaches ``action``'s service.

    A hook's keys reach the service's pool through the edge's overlay, which
    ``check_seeds`` cannot see, so a decorated service action on such a viewset
    is not asked it, as a standalone view with one is not
    (``validate_mutation_view_spec``). A viewset with no mutation mixin has no
    catch-all hook at all, so it reads as unhooked, where
    ``is_overridden`` would read it as hooked (test_a_decorated_action_s_seeds'
    test_on_a_resolver_over_drf_s_viewset_it_is_refused_too). One arc to
    coverage, so each disjunct is named: the catch-all hook by
    test_a_catch_all_hook_filling_the_keyword_mounts_and_fills_it, the
    per-action one by test_a_per_action_hook_filling_the_keyword_mounts_and_fills_it.
    """
    base = MutationFlowMixin.get_service_kwargs
    return getattr(view_cls, "get_service_kwargs", base) is not base or hasattr(
        view_cls, f"get_{action}_service_kwargs"
    )


def _validate_action_answers(view_cls: type | MountedView, action: str, handler: Any) -> None:
    """Ask a decorated action's per-action hooks what a standalone view's answers are asked.

    Only a service action dispatches with them, and a selector action's are
    asked as harmlessly as they are ignored. The decorator's own values were
    asked at decoration. A hook beside one is
    refused, since the action would carry two answers and only one is read
    (test_per_action_answers' test_a_decorator_value_beside_a_hook_is_refused).
    """
    label = f"{view_cls.__name__}.{action}"
    hooks = _action_hooks(view_cls, action)
    for name in hooks:
        if getattr(handler, f"_{name}", None) is not None:
            raise ImproperlyConfigured(
                f"{label}: @service_action declares `{name}` and the viewset defines "
                f"get_{action}_{name}, so the action has two. Keep one."
            )
    _validate_success_status(hooks.get("success_status"), label=label)
    _validate_response_finalizer(hooks.get("response_finalizer"), label=label)


def _validate_decorated_actions(view_cls: type | MountedView, *, pool_seeds: PoolSeeds) -> None:
    """Ask each decorated action's spec the kernel's ``check_seeds`` against ``pool_seeds``.

    ``@service_action`` and ``@selector_action`` run before their viewset and
    its ``pool_seeds`` exist, so the seed check of the spec each stamps on its
    handler is the viewset's, at ``as_view()``: a seed the viewset registers
    serves, and a keyword nothing fills, a seed it does not register among
    them, is refused here, naming the action, rather than answering every
    request with a ``TypeError`` (test_a_decorated_action_s_seeds). A service
    action on a viewset whose hook may fill the keyword is not asked
    (``_fills_service_keywords``); a selector action always is, since the edge
    hands a kernel selector no view hook. Only the seed check is asked: the
    decorator asks the rest of what it can know, and a list action is served
    unfiltered, so the ``filter_set`` check of a list view does not apply.
    """
    for action, handler in inspect.getmembers(view_cls, _is_decorated):
        _validate_action_answers(view_cls, action, handler)
        spec: ActionSpec | None = getattr(handler, "_service_spec", None)
        # One arc to coverage, so each conjunct is named: a selector action on
        # a hooked viewset by test_a_service_kwargs_hook_does_not_excuse_it,
        # the hook by test_a_catch_all_hook_filling_the_keyword_mounts_and_fills_it.
        if spec is not None and _fills_service_keywords(view_cls, action):
            continue
        try:
            _check_kernel_seeds(spec or handler._selector_spec, pool_seeds=pool_seeds)
        except ImproperlyConfigured as refusal:
            raise ImproperlyConfigured(f"{view_cls.__name__}.{action}: {refusal}") from refusal


def _lookup_capture(view_cls: MountedView) -> str:
    """The name a DRF router captures a detail route's lookup under.

    ``lookup_url_kwarg``, else ``lookup_field``, else ``"pk"``, read as
    ``SimpleRouter.get_lookup_regex`` reads them, so the name checked is the
    one the route hands the view.
    """
    return getattr(view_cls, "lookup_url_kwarg", None) or getattr(view_cls, "lookup_field", "pk")


def _mapped_specs(
    view_cls: MountedView, actions: Mapping[str, str]
) -> list[tuple[str, ActionSpec]]:
    """Each action ``actions`` maps a method to, and the spec serving it, where one does.

    The spec ``@service_action`` or ``@selector_action`` stamped on the
    handler, else the ``action_specs`` entry (``partial_update`` falling back
    to ``update``). An action no spec serves (a DRF handler of the author's)
    has no lookup of this package's to check.
    """
    specs: list[tuple[str, ActionSpec]] = []
    for action in dict.fromkeys(actions.values()):
        handler: Any = getattr(view_cls, action, None)
        if _is_decorated(handler):
            spec = getattr(handler, "_service_spec", None) or handler._selector_spec
        else:
            spec = resolve_action_spec_entry(view_cls.action_specs, action)
        if spec is not None:
            specs.append((action, spec))
    return specs


def _row_lookup(spec: ActionSpec) -> KernelSelectorSpec | None:
    """The selector that finds the one row ``spec`` acts on, or ``None`` where it finds none.

    A selector spec is its own lookup; a write's is its ``instance_selector_spec``,
    which the kernel hands only its own parameters, so a capture another of
    the write's parameters declares never reaches the row. A write over a set
    (``collection_selector_spec``) or a list body (``many``) looks up no row.
    """
    if isinstance(spec, KernelSelectorSpec):
        return spec
    return spec.instance_selector_spec


def _validate_lookup_captures(
    view_cls: MountedView, actions: Mapping[str, str] | None, initkwargs: Mapping[str, Any]
) -> None:
    """Refuse a router-mounted detail route whose row lookup declares no parameter for the capture.

    A route capture reaches a spec only as a parameter it declares (the edge's
    ``kernel_arguments``), so a retrieve selector, or a write's target
    selector, that does not read the capture the router builds is never handed
    it: the row is looked up without its key at every request. Refused here
    instead, naming the viewset, the action, the capture and the read that
    serves it (test_lookup_captures). Asked only where a router mounts the
    detail route, which DRF's ``SimpleRouter`` marks by handing ``detail=True``
    to ``as_view()``, and only of the actions it maps there: a viewset mounted
    by hand on a route of its own (a ``me/`` retrieve) has the URLconf's
    captures, which ``as_view()`` cannot see, as a standalone view has. A
    write that looks up no row has no capture to miss (``_row_lookup``).
    """
    if initkwargs.get("detail") is not True or not actions:
        return
    capture = _lookup_capture(view_cls)
    for action, spec in _mapped_specs(view_cls, actions):
        lookup = _row_lookup(spec)
        # One arc to coverage, so each conjunct is named: a write looking up
        # no row by test_a_write_over_a_set_or_a_list_body_looks_up_no_row,
        # the read by test_a_target_selector_reading_the_capture_mounts.
        if lookup is not None and lookup.parameters().get(capture) is None:
            raise ImproperlyConfigured(
                f"{view_cls.__name__}.{action}: the router captures the lookup as "
                f"{capture!r} (lookup_url_kwarg, else lookup_field), and the selector "
                "finding the row declares no parameter of that name, so the capture "
                "never reaches it. Declare it on that selector: "
                f'reads=Parameters.of(Parameter("{capture}", ..., required=True)), '
                "or set lookup_url_kwarg to the name it reads."
            )


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

    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS
    """The seeds the spec's callables are resolved with: the kernel's
    ``DEFAULT_POOL_SEEDS`` unless the view registers others, as a class
    attribute or as ``as_view(pool_seeds=...)``. One registry for the view's
    life: ``as_view()`` checks the spec against it, refusing a callable that
    requires a seed it does not register, and every call's checks, target
    lookup and ``dispatch`` are handed that object (test_pool_seeds)."""

    # Provided by ``GenericAPIView`` / ``ViewSetMixin`` at runtime.
    action: str | None
    action_map: dict[str, str]
    kwargs: dict[str, Any]
    request: Any

    @classmethod
    def as_view(cls, *args: Any, **initkwargs: Any) -> Any:
        # Checked as the instances will be, keywords included: an
        # ``action_specs`` handed here is the one the mixins dispatch, and is
        # this viewset's ``as_view(spec=...)`` (``mounted_view``).
        mounted = mounted_view(cls, initkwargs)
        pool_seeds = view_pool_seeds(mounted)
        for action, spec in mounted.action_specs.items():
            _validate_action_spec(mounted, action, spec, pool_seeds=pool_seeds)
        _validate_decorated_actions(mounted, pool_seeds=pool_seeds)
        actions = args[0] if args else initkwargs.get("actions")
        _validate_lookup_captures(mounted, actions, initkwargs)
        return super().as_view(*args, **initkwargs)  # ty: ignore[unresolved-attribute]

    def options(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        """Answer OPTIONS from the kernel specs the route serves, or as DRF does.

        A route serving any spec is described from its specs (``spec_options``):
        no spec stage runs, and only a method a spec serves is described. A
        route serving none answers as DRF does. A view overriding ``options()``
        without calling ``super()`` gets DRF's own answers.
        """
        served = self._kernel_specs_served()
        if served:
            return spec_options(self, request, served)
        return super().options(request, *args, **kwargs)  # ty: ignore[unresolved-attribute]

    def _kernel_specs_served(self) -> dict[str, KernelServiceSpec | KernelSelectorSpec]:
        """Each method the route maps to an action served by a kernel spec, and that spec.

        Read through ``resolve_action_spec``, as dispatch resolves a spec, so the
        ``"partial_update"`` to ``"update"`` fallback and a spec stamped by
        ``@service_action`` or ``@selector_action`` are both served here too.
        Empty where the view has no action map: built other than by
        ``as_view(actions)``.
        """
        served: dict[str, KernelServiceSpec | KernelSelectorSpec] = {}
        for method, action in getattr(self, "action_map", {}).items():
            spec = resolve_action_spec(self, action)
            if spec is not None:
                served[method.upper()] = spec
        return served

    @property
    def allowed_methods(self) -> list[str]:
        """DRF's, less a method this package's own handler would refuse, on a spec route.

        DRF lists every method the action map binds a handler to, so a router
        mapping PUT to ``update`` on a viewset with no ``update`` spec put PUT
        in ``Allow`` while the handler answers 405. On a route serving a
        spec, a method bound to a handler marked
        ``dispatches_action_specs`` with no spec behind it is left out, which
        ``Allow`` on every response and OPTIONS' ``actions`` both read
        (test_options_metadata's test_allow_names_only_the_methods_a_spec_serves).
        A handler the view defines itself, and the list and retrieve handlers,
        which fall back to DRF's own queryset, stay.
        """
        methods: list[str] = super().allowed_methods  # ty: ignore[unresolved-attribute]
        return [method for method in methods if not self._refuses_without_a_spec(method)]

    def _refuses_without_a_spec(self, method: str) -> bool:
        """Whether ``method`` is left out of ``Allow``: one rule, read by the schema too.

        True on a route serving a spec, for a method reaching one of this
        package's dispatchers with no spec behind it. ``ServiceAutoSchema``
        leaves such a method out of the schema by this same predicate, because
        drf-spectacular reads the router's action map and never ``Allow``
        (test_spec_less_actions).
        """
        # The cheap per-method question first: ``Allow`` asks this on every response.
        return self._refuses(method.lower()) and bool(self._kernel_specs_served())

    def _refuses(self, method: str) -> bool:
        """Whether ``method`` reaches one of this package's dispatchers with no spec to serve it."""
        # ``""`` for a method the action map does not bind (``options``, which
        # DRF serves itself), so the lookups below answer "not refused"
        # without a branch of its own. One arc to coverage, so each condition
        # is named: the marker by test_allow_keeps_a_views_own_handler_without_a_spec,
        # the missing spec by test_allow_names_only_the_methods_a_spec_serves.
        action = getattr(self, "action_map", {}).get(method, "")
        marked = getattr(getattr(self, action, None), "_dispatches_action_specs", False)
        return marked and resolve_action_spec(self, action) is None
