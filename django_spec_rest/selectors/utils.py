"""Internal selector dispatch helpers (sync + async)."""

from __future__ import annotations

import weakref
from collections.abc import Callable, Mapping
from typing import Any

from django.db.models import Model
from django.http import QueryDict
from django_service_specs.adapters.filters.filter_set_parameters import filter_set_parameters
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.parameters.coerce_flat import coerce_flat
from django_service_specs.parameters.parameters import Parameters

# The kernel's own. Re-exported under ``as`` because this module is the path drfs
# has always exported them from, and ``dispatch/`` and the views still import them
# from here.
from django_service_specs.selectors.amaterialize_retrieve import (
    amaterialize_retrieve as amaterialize_retrieve,
)
from django_service_specs.selectors.arun_selector import arun_selector as arun_selector
from django_service_specs.selectors.is_queryset import is_queryset as is_queryset
from django_service_specs.selectors.materialize_retrieve import (
    materialize_retrieve as materialize_retrieve,
)
from django_service_specs.selectors.run_selector import run_selector as run_selector
from django_service_specs.selectors.shape_queryset import shape_queryset
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.settings import api_settings

from django_spec_rest.dispatch.dispatch_spec import dispatch_spec
from django_spec_rest.dispatch.kernel_edge import KernelSpec, dispatch_kernel_spec, runs_on_kernel
from django_spec_rest.types.argument_binding import ArgumentBinding
from django_spec_rest.types.selector_kind import SelectorKind
from django_spec_rest.types.selector_spec import SelectorSpec
from django_spec_rest.views.utils import resolve_view_hooks, view_call_context


def apply_queryset_shaping(
    qs: Any,
    view: Any,
    request: Request,
    *,
    select_related: Any,
    prefetch_related: Any,
    annotations: Any,
    extend_queryset: Any,
    filter_set: Any = None,
    filter_data: Any = None,
    source_label: str,
) -> Any:
    """Apply the five shaping fields to ``qs``, through the kernel's ``shape_queryset``.

    drfs' signature over django-service-specs' shaping, for a caller holding a
    view and a request rather than a spec: the fields become a kernel
    ``SelectorSpec`` (with a stand-in selector it never runs), and ``view``,
    ``request`` and the filter's arguments its pool. The order is the kernel's:
    the declarative fields first (in declaration order), then
    ``extend_queryset``, so the user callable always sees the fully
    statically-shaped queryset, and finally ``filter_set``, so filtering
    composes with shaping and runs before the retrieve ``.first()``
    materialization the caller does next.

    Args:
        extend_queryset: Called as ``extend_queryset(qs, view, request)``, by
            position, as it always was; the kernel binds its own by name.
        filter_set: A django-filter ``FilterSet``, validated before ``.qs`` is
            read, and handed ``request`` through its constructor, so a
            request-scoped one sees the ``self.request`` it would behind
            ``DjangoFilterBackend``.
        filter_data: The mapping the filter's arguments are read from, each of
            its filters' names and nothing else. ``None`` falls back to
            ``request.query_params``, the HTTP view path. A ``QueryDict`` is
            read flat as dispatch reads a query string: a repeated key as a list
            where the filter takes several values, and each value coerced to the
            type the filter declares.
        source_label: Named in the misconfiguration error to point at the
            offending callable (``"SelectorSpec.selector"`` vs
            ``"ServiceSpec.output_selector_spec.selector"``).

    Returns:
        The shaped queryset, or ``qs`` unchanged when nothing is configured.

    Raises:
        ImproperlyConfigured: Shaping is configured but ``qs`` is not a Django
            queryset; ``filter_set`` is not a django-filter ``FilterSet`` (one
            duck-typed on ``(data, queryset) -> .qs`` is refused); or
            ``extend_queryset`` answered with an awaitable.
        InvalidArguments: The kernel's, where ``filter_set`` refused its data or
            a value no integer column can hold, keyed as the ``FilterSet`` keys
            its errors. It reaches the caller as the kernel raised it, not as
            DRF's ``ValidationError``: nothing here translates it, so a caller
            inside a DRF view that wants a 400 translates it itself.
    """
    spec = KernelSelectorSpec(
        kind=SelectorKind.LIST,
        selector=_never_run,
        select_related=select_related,
        prefetch_related=prefetch_related,
        annotations=annotations,
        extend_queryset=_positional(extend_queryset) if extend_queryset is not None else None,
        filter_set=filter_set,
    )
    pool: dict[str, Any] = {"view": view, "request": request}
    if filter_set is not None:
        source = filter_data if filter_data is not None else request.query_params
        pool.update(_filter_arguments(filter_set_parameters(filter_set), source))
    return shape_queryset(qs, spec, pool, source_label=source_label)


def _never_run() -> None:
    """The selector the kernel's spec requires; shaping never calls it."""


def _positional(extend: Callable[..., Any]) -> Callable[..., Any]:
    """drfs' positional ``extend_queryset`` as a callable the kernel binds by name.

    No ``functools.wraps``: it sets ``__wrapped__``, which ``inspect.signature``
    follows, and the kernel would read the wrapped callable's own names.
    """

    def extend_queryset(queryset: Any, view: Any, request: Any) -> Any:
        return extend(queryset, view, request)

    return extend_queryset


def _filter_arguments(parameters: Parameters, source: Mapping[str, Any]) -> dict[str, Any]:
    """The filter's own names in ``source``; a ``QueryDict`` read flat and coerced.

    A ``QueryDict`` holds a list per key, so each name takes every value where
    its Parameter is an array and the last one otherwise, as ``QueryDict``
    reads a repeated key, then ``coerce_flat`` reads the strings as their
    declared types. Held by
    ``test_a_repeated_query_key_reaches_a_multi_valued_filter_whole`` and
    ``test_filter_data_replaces_the_query_string`` (a plain mapping).
    """
    present = [param for param in parameters if param.name in source]
    if not isinstance(source, QueryDict):
        return {param.name: source[param.name] for param in present}
    flat = {
        param.name: source.getlist(param.name) if param.type == "array" else source.get(param.name)
        for param in present
    }
    return coerce_flat(parameters, flat)


def check_view_object_permissions(
    spec: Any,
    context: Any,
    *,
    instance: Any = None,
) -> None:
    """[`TargetGuard`][django_spec_rest.types.target_guard.TargetGuard] running
    DRF's object-permission check for an HTTP view.

    The HTTP counterpart of
    [`enforce_permissions`][django_spec_rest.dispatch.enforce_permissions.enforce_permissions]:
    off HTTP a transport enforces ``spec.permission_classes`` itself, while a DRF view
    has already instantiated them and exposes ``check_object_permissions``. Both plug
    into the same ``on_target_resolved`` seam, so the core stays authz-agnostic on every
    transport.

    Gated on ``Model``, like ``enforce_permissions``: the core fires this hook on
    the LIST branch too, with the resolved **queryset**, and object permissions
    are per-row. ``None`` — a create, or a bulk list payload — is skipped too.
    """
    if isinstance(instance, Model):
        context.view.check_object_permissions(context.request, instance)


def dispatch_selector_for_spec(view: Any, spec: SelectorSpec[Any, Any]) -> Any:
    """End-to-end dispatch for one ``SelectorSpec`` call from a DRF view.

    Resolves the view's ``get_selector_kwargs`` / ``get_<action>_selector_kwargs`` chain
    into a [`ViewHooks`][django_spec_rest.types.view_hooks.ViewHooks] carrier,
    hands off to the one
    [`dispatch_spec`][django_spec_rest.dispatch.dispatch_spec.dispatch_spec]
    core, and translates the neutral
    [`DispatchResult`][django_spec_rest.types.dispatch_result.DispatchResult]
    into the view-layer contract: a RETRIEVE that resolved nothing raises ``NotFound``,
    unless the spec sets ``allow_none=True`` (then ``None``, and the retrieve views
    render 200 + JSON ``null``). ``SelectorKind.LIST`` returns the shaped queryset.

    **The request is no argument mapping.** Off HTTP the flat ``params``
    mapping *is* the argument channel; over HTTP it is empty, and a selector's
    arguments come from what the spec declares it reads: a route capture of
    one of its reads or a declared ``UrlKwarg`` from ``view.kwargs``, a
    declared ``QueryParam`` from the query string, and the hook chain's values.
    The query string reaches the ``filter_set`` as ``filter_data``, restricted
    to the names the filter reads, so it feeds the filter without widening the
    argument channel.

    There is deliberately no ``extra_url_kwargs`` parameter: the core reads
    ``view.kwargs`` itself, for the names the spec reads and the ones its
    callables mark ``NotClientInput``, and a capture named like a seed of the
    call never replaces the seed, so a nested route like
    ``/users/<user>/posts/`` cannot let the captured value shadow the
    authenticated ``user`` (test_url_kwarg_cannot_shadow_the_authenticated_user_over_http).
    Taking the mapping from a caller would reopen that.

    The caller must check ``spec.selector is not None`` first and fall back to
    vanilla DRF otherwise.
    """

    assert spec.selector is not None  # noqa: S101 — caller guarantees this
    request = view.request
    if runs_on_kernel(spec):
        # A kernel spec parts from the drfs path here, and its callers read the
        # value alone; the query views, which present it, take the whole result
        # from ``dispatch_kernel_selector``.
        return dispatch_kernel_selector(view, spec).value
    result = dispatch_spec(
        spec,
        user=getattr(request, "user", None),
        params={},
        filter_data=request.query_params,
        request=request,
        view=view,
        argument_binding=ArgumentBinding.BUNDLE,
        on_target_resolved=check_view_object_permissions,
        view_hooks=resolve_view_hooks(view, request, chain="selector"),
        # The request's one dict, so the spec's own providers share it with the
        # view's hooks and the render
        # (test_a_selector_spec_s_kwargs_provider_shares_the_view_s_context).
        call_context=view_call_context(view, request),
    )
    if result.kind == "not_found":
        raise NotFound()
    return result.value


def dispatch_kernel_selector(view: Any, spec: KernelSpec) -> DispatchResult:
    """Run a kernel ``spec`` for a selector view's request, the result whole.

    A selector spec, which ``as_view()`` holds every selector view to; typed
    as either kernel spec because ``runs_on_kernel`` is the one fact its
    caller parts on.

    The kernel's own ``dispatch`` reads the query string and the declared route
    captures (``dispatch_kernel_spec``); a RETRIEVE that found nothing raises
    ``NotFound``, so what comes back is always presentable: a row, a set, or
    ``None`` under ``allow_none``. The result rather than its value, so the
    query views present it through the spec's own presenter, with the context
    dispatch built for it.

    **The view's object permission is asked inside the dispatch**, as one of
    the spec's checks (``_viewed``), so it runs where the kernel asks its own
    object-level checks: on the row the selector found, before the spec's
    ``preconditions`` and before anything is presented. A principal the view
    refuses the row is answered 403 and never told what a precondition over it
    says (test_the_view_s_object_permission_is_asked_before_the_preconditions),
    as DRF's ``get_object()`` asks it before anything reads the row.
    """
    found = dispatch_kernel_spec(
        _viewed(spec),
        view=view,
        request=view.request,
        call_context=view_call_context(view, view.request),
    )
    if found.kind == "not_found":
        raise NotFound()
    return found


class _ViewObjectPermission(PermissionCheck):
    """The view's own ``check_object_permissions``, as a kernel check.

    Class-level it allows: DRF's ``initial()`` has asked the view's
    ``has_permission`` before the handler ran. Object-level it asks the view
    of the row, through the call's context, which carries the request and the
    view the edge filled, so one instance serves every request. A refusal
    leaves as DRF's own ``PermissionDenied`` or ``NotAuthenticated``, raised
    inside the kernel's check and passed on by the edge as DRF's already, so
    the 401 or 403 is the one DRF's ``get_object()`` answers
    (test_an_anonymous_caller_refused_the_row_is_asked_to_authenticate).
    """

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True

    def has_object_permission(
        self,
        principal: Any,
        spec: Any,
        target: Any,
        *,
        call_context: Mapping[str, Any] | None = None,
    ) -> bool:
        # The kernel hands every check declaring ``call_context`` the call's
        # dict, so ``None`` is a caller asking outside a dispatch, with no view
        # to ask: refused, never allowed unasked
        # (test_the_view_s_check_asked_with_no_call_context_refuses).
        if call_context is None:
            return False
        # Per-row, as DRF's ``get_object()`` and the drfs path's target hook
        # ask it: a value that is no model row, a dataclass or a mapping a
        # selector built, is handed to no DRF class's ``has_object_permission``,
        # which would read ``obj._meta`` off it
        # (test_a_row_that_is_no_model_is_not_asked_of_the_view).
        if isinstance(target, Model):
            call_context["view"].check_object_permissions(call_context["request"], target)
        return True


_VIEW_OBJECT_PERMISSION = _ViewObjectPermission()

_VIEWED: dict[int, tuple[weakref.ref[KernelSpec], KernelSpec]] = {}
"""Each spec's twin carrying the view's object permission, by the spec's identity.

Built once per spec, since ``derive`` re-runs the spec's checks, and keyed and
held as ``recording_spec`` holds its twins: by ``id``, a weak reference to the
spec dropping the entry when the spec dies."""


def _viewed(spec: KernelSpec) -> KernelSpec:
    """``spec`` with the view's object permission first among its ``permissions``.

    First, as DRF asks the view's own permission classes before anything of
    the spec's. A spec declaring no ``permissions`` is dispatched as it is, so
    the kernel still refuses it as declaring none: adding the view's check
    would make it look guarded (test_a_spec_declaring_no_permissions_is_still_refused).
    """
    if spec.permissions is None:
        return spec
    key = id(spec)
    cached = _VIEWED.get(key)
    if cached is not None and cached[0]() is spec:
        return cached[1]
    twin = spec.derive(permissions=(_VIEW_OBJECT_PERMISSION, *spec.permissions))
    _VIEWED[key] = (weakref.ref(spec, lambda _dead: _VIEWED.pop(key, None)), twin)
    return twin


def drf_query_keys(view: Any) -> frozenset[str]:
    """The query-string keys DRF's own machinery reads on ``view``, not the spec.

    ``URL_FORMAT_OVERRIDE`` (``?format``), and every string attribute named
    ``*_param`` on the view's paginator and on each of its filter backends'
    classes: ``page_query_param``, ``page_size_query_param``,
    ``limit_query_param``, ``offset_query_param`` and ``cursor_query_param``
    on DRF's three paginators, ``search_param`` and ``ordering_param`` on its
    two filters, ``version_param`` on its query-parameter versioning, and the
    same spelling on a project's own. A ``None`` or a blank, a reader's way of
    reading no such key, names none (test_drf_query_keys, its ``_OwnFilter``
    row holding the blank). A view-level ``DjangoFilterBackend`` reading a
    ``filterset_fields`` of the view's own is not read here: its keys are its
    filter set's, which only its ``get_filterset_class(view, queryset)``
    knows. Read off the classes
    and the configured paginator alone, never through a backend's schema
    method, since django-filter's calls ``view.get_queryset()``, which is the
    dispatch these keys are read for.
    """
    keys: set[str] = set()
    if api_settings.URL_FORMAT_OVERRIDE:
        keys.add(api_settings.URL_FORMAT_OVERRIDE)
    readers = [
        getattr(view, "paginator", None),
        getattr(view, "versioning_class", None),
        *getattr(view, "filter_backends", ()),
    ]
    for reader in readers:
        for name in dir(reader):
            value = getattr(reader, name, None) if name.endswith("_param") else None
            if isinstance(value, str) and value:
                keys.add(value)
    return frozenset(keys)


def kernel_query(view: Any, spec: KernelSelectorSpec, request: Request) -> QueryDict:
    """``request.query_params`` without the keys DRF reads on ``view``, for the kernel.

    A copy: the paginator and the filter backends read the request's own
    after the dispatch, so ``?page=2`` still turns the page. A key the spec
    declares as a parameter stays, whatever reads it beside the spec: a
    declared read is the spec's
    (test_a_read_named_like_a_drf_key_is_still_the_spec_s).
    """
    declared = spec.parameters()
    query = request.query_params.copy()
    for key in drf_query_keys(view):
        if declared.get(key) is None:
            query.pop(key, None)
    return query
