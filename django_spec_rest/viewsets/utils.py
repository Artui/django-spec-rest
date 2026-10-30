"""Shared infrastructure for viewset mixins."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, ClassVar, TypeVar

from django.core.exceptions import ImproperlyConfigured
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from rest_framework.exceptions import MethodNotAllowed

from django_spec_rest.views.mutation.utils import _ServesRaisedSchema
from django_spec_rest.views.spec_options import spec_options
from django_spec_rest.views.spec_validation import (
    validate_mutation_view_spec,
    validate_selector_view_spec,
)

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


def _as_mounted(view_cls: type, action: str, spec: object, *, label: str) -> type:
    """``view_cls`` as a standalone view would carry ``spec``: on ``spec``, serving ``action``.

    The standalone views' kernel checks (``validate_mutation_view_spec`` and
    ``validate_selector_view_spec``) read the spec, the view's hooks, its
    ``success_status`` and ``response_finalizer`` and the ``action`` its
    per-action hooks are named for, all off the class. A subclass of the
    viewset carrying the entry as its ``spec`` and the key as its ``action``
    answers each of those as the viewset does for that action, so the entry
    is asked exactly what the standalone view asks of its spec, the checks
    added to those entry points included, rather than a copy of them. Named
    after the entry, so a refusal names the action it is about
    (test_service_viewset's test_the_refusal_names_the_action).
    """
    return type(label, (view_cls,), {"spec": spec, "action": action})


def _validate_kernel_action_spec(
    view_cls: type, action: str, spec: KernelServiceSpec | KernelSelectorSpec, *, label: str
) -> None:
    """Ask a kernel entry the checks a standalone view asks of its kernel ``spec``.

    A built-in write action is asked as the matching mutation view is
    (``has_instance`` for an update or a delete, so a spec naming no target is
    refused), and a read action as the matching selector view is, the
    ``kind`` included. A kernel spec under the other kind of action is refused
    by those same checks.

    **A custom key is refused.** Such an entry feeds ``get_permissions`` and
    the serializer resolver alone, while a kernel spec declares no
    ``permission_classes`` and its own checks are asked by ``dispatch``, which
    a custom key never reaches: the entry would guard nothing it seems to.
    ``@service_action`` and ``@selector_action`` serve one
    (test_service_viewset's test_a_kernel_spec_under_a_custom_key_is_refused).
    """
    mounted = _as_mounted(view_cls, action, spec, label=label)
    if action in _MUTATION_ACTIONS:
        validate_mutation_view_spec(mounted, has_instance=_MUTATION_ACTIONS[action]["has_instance"])
    elif action in _SELECTOR_ACTION_KIND:
        validate_selector_view_spec(
            mounted,
            expected_kind=_SELECTOR_ACTION_KIND[action],
        )
    else:
        raise ImproperlyConfigured(
            f"{label} is a kernel {type(spec).__name__} under a key no action of the "
            "viewset dispatches, so its permissions would guard nothing. Serve it with "
            "@service_action(spec) or @selector_action(spec) on the action's method."
        )


def _validate_action_spec(view_cls: type, action: str, spec: object) -> None:
    """Run fail-fast validation for a single ``action_specs`` entry.

    Every entry is validated, whatever it is keyed on.
    """
    label = f"{view_cls.__name__}.action_specs[{action!r}]"
    if not isinstance(spec, KernelServiceSpec | KernelSelectorSpec):
        raise ImproperlyConfigured(
            f"{label} must be a ServiceSpec or SelectorSpec, got {type(spec).__name__}."
        )
    _validate_kernel_action_spec(view_cls, action, spec, label=label)


class _ActionSpecsMixin(_ServesRaisedSchema):
    """Declares the ``action_specs`` class attribute shared by all viewset mixins.

    All per-action mixins and
    [`ActionSerializerResolver`][django_spec_rest.viewsets.action_serializer_resolver.ActionSerializerResolver]
    inherit from this so the attribute is defined in exactly one place. ``as_view`` runs
    fail-fast spec validation once per view at URL-wiring time.

    A kernel spec declares no ``permission_classes``: its checks are its
    ``permissions``, which the kernel's ``dispatch`` asks after DRF has asked the
    view's own (test_service_viewset's
    test_the_view_s_own_classes_refuse_before_the_spec_runs).
    """

    action_specs: ClassVar[Mapping[str, ActionSpec]] = {}

    # Provided by ``GenericAPIView`` / ``ViewSetMixin`` at runtime.
    action: str | None
    action_map: dict[str, str]
    kwargs: dict[str, Any]
    request: Any

    @classmethod
    def as_view(cls, *args: Any, **initkwargs: Any) -> Any:
        for action, spec in cls.action_specs.items():
            _validate_action_spec(cls, action, spec)
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
        if not self._kernel_specs_served():
            return methods
        return [method for method in methods if not self._refuses(method.lower())]

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
