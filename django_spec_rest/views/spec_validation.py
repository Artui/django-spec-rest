"""Fail-fast validation of a view's kernel spec at view setup time.

A kernel spec checks its own fields when it is built, so ``as_view()`` asks
only what the view knows: that the spec is of the kind of operation the view
serves, the ``SelectorKind`` its mount point is shaped for, and no
``filter_set`` beside DRF's own filter backend on a list; then the kernel's
``check_seeds``, against the seeds the edge dispatches with, refuses whatever
no call could fill. A required parameter nothing can fill is met at
``as_view()`` rather than as a bare ``TypeError`` deep in dispatch at the first
request. No view hook reaches a kernel spec, so nothing is lenient on extras.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django_service_specs.dispatch.check_seeds import check_seeds
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from django_service_specs.types.selector_kind import SelectorKind

from django_spec_rest.service_specs.serializer_validator import SerializerValidator


def _required_kw_params(fn: Callable[..., Any]) -> dict[str, inspect.Parameter]:
    """Return the kw-resolvable params of ``fn`` with no default, keyed by name.

    A parameter with a default is optional from the framework's point of view.
    """
    sig = inspect.signature(fn)
    return {
        name: p
        for name, p in sig.parameters.items()
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        and p.default is inspect.Parameter.empty
    }


def _positional_only(fn: Callable[..., Any]) -> list[str]:
    """The parameters of ``fn`` taking a value by position alone and declaring no default, sorted.

    The framework hands every value by keyword (``resolve_callable_kwargs``),
    so such a parameter is never supplied, whatever its name: called, ``fn``
    raises ``TypeError``. One with a default is left to it. One branch to
    coverage, so each condition is named: a keyword parameter by
    test_create_returns_201_then_200_on_upsert, which every parameter would
    otherwise refuse, and a default by
    test_a_positional_only_parameter_with_a_default_is_left_to_it.
    """
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


def is_overridden(view_cls: type, base_cls: type, method_name: str) -> bool:
    """Return ``True`` if ``view_cls`` overrides ``base_cls``'s ``method_name``.

    Drives ``permissive_extras``: an overridden ``get_*_kwargs`` is assumed to
    contribute keys the validator cannot see.
    """
    base = getattr(base_cls, method_name, None)
    if base is None:
        return hasattr(view_cls, method_name)
    return getattr(view_cls, method_name, None) is not base


def _uses_django_filter_backend(view_cls: type) -> bool:
    """True when ``view_cls.filter_backends`` includes a ``DjangoFilterBackend``.

    Matched by name across each backend's MRO (so subclasses count) rather than
    ``isinstance``: ``django-filter`` is an optional dependency this package
    never imports, so the check has to hold whether or not it is installed.
    """
    backends = getattr(view_cls, "filter_backends", None) or ()
    return any(
        any(
            getattr(klass, "__name__", "") == "DjangoFilterBackend"
            for klass in getattr(backend, "__mro__", ())
        )
        for backend in backends
    )


def validate_filter_set_no_backend_conflict(
    view_cls: type,
    spec: KernelSelectorSpec,
    *,
    label: str,
) -> None:
    """Reject a list selector that sets ``filter_set`` *and* wires ``DjangoFilterBackend``.

    On the list path DRF's ``list()`` runs ``filter_queryset()`` while the
    dispatcher also applies ``spec.filter_set`` — equivalent operations, so the
    queryset would be filtered twice. Callers must gate this on the **list** path
    only: the selector retrieve path overrides ``get_object()`` and never calls
    ``filter_queryset``, so there is no conflict there. A kernel spec's
    ``filter_set`` is applied by the kernel's dispatch the same way, so it is
    asked of either.
    """
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


def _validate_success_status(
    success_status: int | Callable[..., int] | None, *, label: str
) -> None:
    """Reject a ``success_status`` that is neither int/None nor a well-formed callable.

    A required parameter outside ``_SUCCESS_STATUS_KEYS`` can never be
    supplied, so it fails here rather than as a ``TypeError`` deep in dispatch,
    ``**kwargs`` beside it or not: ``**kwargs`` is handed the pool, never a
    name the pool lacks
    (test_a_callable_taking_kwargs_beside_a_key_the_pool_lacks_is_refused_at_as_view).
    Nor can a required positional-only parameter, a key's name included
    (test_a_callable_taking_a_positional_only_parameter_is_refused_at_as_view).
    """
    if success_status is None or isinstance(success_status, int):
        return
    if not callable(success_status):
        raise ImproperlyConfigured(
            f"{label}: `success_status` must be an int, a callable returning an int, "
            f"or None — got {type(success_status).__name__}."
        )
    _refuse_positional_only(success_status, label=label, seat="success_status")
    unknown = set(_required_kw_params(success_status)) - _SUCCESS_STATUS_KEYS
    if unknown:
        raise ImproperlyConfigured(
            f"{label}: `success_status` callable requires parameter(s) "
            f"{sorted(unknown)} the framework can't supply — declare only a subset "
            f"of {sorted(_SUCCESS_STATUS_KEYS)}, and `**kwargs` for the rest."
        )


def _validate_response_finalizer(finalizer: Any, *, label: str) -> None:
    """Reject a ``response_finalizer`` that isn't a well-formed callable.

    Same rule as ``_validate_success_status``, against
    ``_RESPONSE_FINALIZER_KEYS``
    (test_a_finalizer_taking_kwargs_beside_a_key_the_framework_lacks_is_refused_at_as_view,
    test_a_finalizer_taking_a_positional_only_parameter_is_refused_at_as_view).
    """
    if finalizer is None:
        return
    if not callable(finalizer):
        raise ImproperlyConfigured(
            f"{label}: `response_finalizer` must be a callable returning a Response "
            f"or None — got {type(finalizer).__name__}."
        )
    _refuse_positional_only(finalizer, label=label, seat="response_finalizer")
    unknown = set(_required_kw_params(finalizer)) - _RESPONSE_FINALIZER_KEYS
    if unknown:
        raise ImproperlyConfigured(
            f"{label}: `response_finalizer` requires parameter(s) {sorted(unknown)} the "
            f"framework can't supply — declare only a subset of "
            f"{sorted(_RESPONSE_FINALIZER_KEYS)}, and `**kwargs` for the rest."
        )


def _validate_selector_kind(
    spec: KernelSelectorSpec,
    *,
    label: str,
    expected_kind: SelectorKind,
) -> None:
    """Reject a spec whose ``kind`` is not the one its mount point is shaped for.

    The kind is the view's question, which no check made when the spec was built
    can answer.
    """
    if spec.kind is not expected_kind:
        raise ImproperlyConfigured(
            f"{label}: spec.kind is {spec.kind!r} but this mount point "
            f"expects {expected_kind!r}. Construct the spec with "
            f"kind={expected_kind!r} or move it to the matching view."
        )


def _serves_the_other_kind(view_cls: type, spec: Any, served: type) -> str:
    """Why ``view_cls`` refuses ``spec``: a kernel spec of the kind the view does not serve."""
    return (
        f"{view_cls.__name__}.spec is a {type(spec).__name__}, but this view serves a "
        f"{served.__name__}. Set the spec on a view of its own kind."
    )


def _check_kernel_seeds(spec: KernelServiceSpec | KernelSelectorSpec) -> None:
    """Refuse at ``as_view()`` what the kernel's ``check_seeds`` refuses of ``spec``.

    It answers the questions a spec's signatures raise: a keyword nothing
    fills, a positional-only parameter, an optional read over a keyword that
    requires it, a parameter a seed occupies. Not every one: ``check_seeds``
    reads no output selector, so a keyword an ``output_selector_spec``'s
    selector requires and nothing fills is met only when the call reaches the
    re-read, after the service has run. It is asked with the kernel's default seeds because
    those are the seeds the edge dispatches with (``dispatch_kernel_spec``
    registers none), and only where nothing fills a keyword it cannot see:
    a mutation view overriding a service-kwargs hook hands the edge's
    overlay keys ``check_seeds`` never reads, so such a view is not asked it
    (``validate_mutation_view_spec``), and a selector view overriding
    ``get_selector_kwargs`` is refused beside a kernel spec
    (``_refuse_selector_hooks``), so a selector view has no overlay to hide
    a keyword.
    The fields a kernel spec declares are checked when it is built, by its own
    ``__post_init__``, so no field check is owed here.
    Held on a mutation view by test_a_keyword_nothing_fills_is_refused and on
    a selector view by test_a_list_selector_requiring_data_is_refused.

    **A serializer that cannot be described at mount is not asked.**
    ``check_seeds`` reads ``spec.parameters()``, which describes a
    ``SerializerValidator``'s serializer, and at ``as_view()`` there is no
    call to describe it with: its context holds ``None`` for the request and
    none of the view's layers. A ``get_fields`` reading
    ``self.context["request"].user`` or a key the view's input layer adds
    would raise from the URLconf's import, so such a spec's checks are its
    first request's, where the kernel answers them as it dispatches
    (test_spec_validation_e2e's TestASerializerThatCannotBeDescribedAtMount).
    Only the description is tried and caught: every refusal ``check_seeds``
    makes of a serializer that describes still raises here
    (test_a_refusal_check_seeds_makes_of_a_describable_spec_still_raises).
    A view overriding ``get_service_kwargs`` or a per-action
    ``get_<action>_service_kwargs`` is not checked either, as
    ``validate_mutation_view_spec`` does not call this for it, so its seeds
    are its first request's as well.
    """
    # A selector spec has no validator to describe; reading one off it raises
    # at as_view() (test_a_var_keyword_selector_reads_no_route_capture and
    # test_url_kwarg_over_http mount selector views at import).
    validator = spec.validator if isinstance(spec, KernelServiceSpec) else None
    if isinstance(validator, SerializerValidator):
        try:
            validator.parameters()
        # Each type is one a serializer raises when described with no call:
        # ``AttributeError`` reading ``.user`` off the ``None`` request
        # (test_one_reading_the_request_s_user_mounts_and_serves), ``KeyError``
        # reading a key only the view's layer adds
        # (test_one_reading_a_key_the_view_s_layer_adds_mounts_and_serves).
        except (AttributeError, KeyError):
            return
    check_seeds(spec)


def refuse_a_nested_selectors_permissions(spec: KernelServiceSpec, *, label: str) -> None:
    """Refuse ``permissions`` declared on a kernel spec's nested selector, on any of its three seats.

    A nested selector is a step of the spec's call, not a call of its own: the
    kernel authorizes the spec being dispatched and never asks the nested
    selector's ``permissions``, so one declared guards nothing and reads as if
    it did. Any declaration is refused, ``Unrestricted()`` included: the
    default is ``None``, which the kernel already refuses an empty sequence
    beside, so a nested selector declaring nothing mounts.

    One arc to coverage, so each conjunct is named: a seat the spec leaves
    unset is skipped by every spec with no nested selector there
    (test_service_create_view's test_creates_and_returns_201), and the
    ``permissions`` test by every nested selector that declares none
    (test_a_nested_selector_declaring_no_permissions_mounts). Each seat is held
    by its own case of test_a_nested_selector_s_permissions_are_refused, since
    coverage cannot see a role dropped from the tuple.
    """
    for role in ("instance", "collection", "output"):
        nested: KernelSelectorSpec | None = getattr(spec, f"{role}_selector_spec")
        if nested is not None and nested.permissions is not None:
            raise ImproperlyConfigured(
                f"{label}.{role}_selector_spec declares permissions, which a nested selector "
                "never has asked: the spec being dispatched is what authorizes. Declare them "
                "on the ServiceSpec, and drop them from the nested selector."
            )


def validate_mutation_view_spec(
    view_cls: type,
    *,
    has_instance: bool,
) -> None:
    """Validate ``view_cls.spec`` on a standalone mutation view.

    No-op when ``spec`` is unset: the base classes inherit a ``None``
    placeholder so ``as_view()`` itself doesn't trip.
    """
    spec: KernelServiceSpec | KernelSelectorSpec | None = getattr(view_cls, "spec", None)
    if spec is None:
        return
    # A kernel selector spec is a kernel spec the kernel dispatches as gladly,
    # so without this a mutation view would run a read for a write
    # (test_kernel_views' test_a_kernel_selector_spec_on_a_mutation_view_is_refused_at_as_view).
    if not isinstance(spec, KernelServiceSpec):
        raise ImproperlyConfigured(_serves_the_other_kind(view_cls, spec, KernelServiceSpec))
    # Local import to avoid a module-level cycle:
    # ``views.spec_validation`` is imported by ``views.mutation.*``, but the
    # reverse coupling only matters here (to detect catch-all overrides).
    from django_spec_rest.views.mutation.mutation_flow_mixin import (
        MutationFlowMixin,
    )

    hooked = is_overridden(view_cls, MutationFlowMixin, "get_service_kwargs")
    # A kernel spec declares neither HTTP answer, so the view's own
    # attributes are what ``_dispatch_kernel_mutation`` calls, after the
    # service has run: refused here rather than as a ``TypeError`` once the
    # write has committed
    # (test_callable_success_status' TestASuccessStatusTheViewCannotResolve,
    # test_response_finalizer's TestAFinalizerTheViewCannotCall). Read off
    # the class, which a function stored there is returned from unbound.
    _validate_success_status(getattr(view_cls, "success_status", None), label=view_cls.__name__)
    _validate_response_finalizer(
        getattr(view_cls, "response_finalizer", None), label=view_cls.__name__
    )
    _refuse_a_detail_spec_with_no_target(view_cls, spec, has_instance=has_instance)
    refuse_a_nested_selectors_permissions(spec, label=f"{view_cls.__name__}.spec")
    # A view hook's keys reach the service through the edge's overlay,
    # which ``check_seeds`` cannot see and its own docstring says not to
    # be asked beside, so a hooked view is not asked it. One arc to coverage, so
    # each disjunct is named: the catch-all hook by test_spec_validation_e2e's
    # test_a_view_hook_fills_a_keyword_check_seeds_cannot_see, the
    # per-action one by test_a_per_action_hook_fills_a_keyword_check_seeds_cannot_see.
    if not (hooked or _overrides_the_action_hook(view_cls, "service")):
        _check_kernel_seeds(spec)


def _refuse_a_detail_spec_with_no_target(
    view_cls: type, spec: KernelServiceSpec, *, has_instance: bool
) -> None:
    """Refuse an update or delete view's kernel spec that names nothing for it to act on.

    A kernel spec never asks the view's ``get_object()`` for its row, since
    the kernel refuses a
    ``target=`` handed to a spec declaring no target selector, so such a spec
    would run on no row at all (test_service_update_view's
    test_a_detail_view_s_kernel_spec_with_no_target_selector_is_refused_at_as_view).
    Asked before ``check_seeds``, whose refusal of a service taking
    ``instance`` would name the symptom rather than the seat.

    One arc to coverage, so each conjunct is named: ``has_instance`` by every
    create view over a spec with no target selector (test_service_create_view's
    test_creates_and_returns_201), ``many`` by a bulk update, whose list body
    is its rows and which the kernel refuses a target selector to
    (test_bulk_mutations' test_an_update_view_takes_a_many_spec_s_list_body_as_its_rows), and
    the target selector by the refusal's own test.
    """
    if has_instance and not spec.many and spec.target_selector_spec() is None:
        raise ImproperlyConfigured(
            f"{view_cls.__name__}.spec declares no target selector, so it would act on no "
            "row: a kernel spec's target is its own lookup's, and the view's get_object() is "
            "never asked for one. Set instance_selector_spec to the row it acts on, "
            "collection_selector_spec to a set, or many=True for a list body."
        )


def _refuse_selector_hooks(view_cls: type) -> None:
    """Refuse a selector view's ``get_selector_kwargs`` hooks beside a kernel spec.

    A kernel selector spec is handed its own ``kwargs`` provider's values and
    no view hook's: the selector views hand the edge no hooks at all, so an
    override would be silently unasked, and a keyword it was written to fill
    a 500 or a default. Refused when the view is built, before
    ``check_seeds`` would name the unfilled keyword rather than the hook. One
    arc to coverage, so each disjunct is named: the catch-all hook by
    test_selector_list_view's
    test_get_selector_kwargs_beside_a_kernel_spec_is_refused_at_as_view, the
    per-action one by
    test_a_per_action_selector_hook_beside_a_kernel_spec_is_refused_at_as_view.
    """
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


def _overrides_the_action_hook(view_cls: type, chain: str) -> bool:
    """Whether ``view_cls`` defines ``get_<action>_<chain>_kwargs`` for the ``action`` it sets.

    A standalone view has no ``action`` unless its class sets one, and the
    view's hook chain asks the per-action hook only for that action
    (``resolve_view_hooks``), so a hook named for any other is never asked
    and fills nothing (test_spec_validation_e2e's
    test_a_per_action_hook_for_another_action_fills_nothing).
    """
    action = getattr(view_cls, "action", None)
    return isinstance(action, str) and hasattr(view_cls, f"get_{action}_{chain}_kwargs")


def validate_selector_view_spec(
    view_cls: type,
    *,
    expected_kind: SelectorKind,
) -> None:
    """Validate ``view_cls.spec`` on a standalone selector view.

    No-op when ``spec`` is unset: that means "use vanilla DRF". ``expected_kind`` is
    the kind the view is shaped for (``LIST`` for
    [`SelectorListView`][django_spec_rest.views.query.selector_list_view.SelectorListView],
    ``RETRIEVE`` for
    [`SelectorRetrieveView`][django_spec_rest.views.query.selector_retrieve_view.SelectorRetrieveView]),
    A ``get_selector_kwargs`` the view has is the author's, since no
    selector view or mixin declares one, and is refused beside a kernel spec.
    """
    spec: KernelSelectorSpec | KernelServiceSpec | None = getattr(view_cls, "spec", None)
    if spec is None:
        return
    label = f"{view_cls.__name__}.spec"
    if not isinstance(spec, KernelSelectorSpec):
        # As ``validate_mutation_view_spec`` refuses a kernel selector spec
        # (test_kernel_views' test_a_kernel_service_spec_on_a_selector_view_is_refused_at_as_view).
        raise ImproperlyConfigured(_serves_the_other_kind(view_cls, spec, KernelSelectorSpec))
    # The spec's own fields are checked by its ``__post_init__``, but two checks
    # are the view's: the kind its mount point is shaped for
    # (test_kernel_views' test_a_list_spec_on_a_retrieve_view_is_refused_at_as_view)
    # and, below, a ``filter_set`` beside DRF's own filter backend
    # (test_a_filter_set_beside_django_filter_s_backend_is_refused_at_as_view).
    _validate_selector_kind(spec, label=label, expected_kind=expected_kind)
    _refuse_selector_hooks(view_cls)
    _check_kernel_seeds(spec)
    if expected_kind is SelectorKind.LIST:
        validate_filter_set_no_backend_conflict(view_cls, spec, label=label)
