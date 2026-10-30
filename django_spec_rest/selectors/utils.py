"""Internal selector dispatch helpers (sync + async)."""

from __future__ import annotations

import dataclasses
import weakref
from collections.abc import Mapping
from typing import Any, cast

from django.db.models import Model
from django.http import QueryDict
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.present import present
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.settings import api_settings
from rest_framework.versioning import QueryParameterVersioning

from django_spec_rest.dispatch.kernel_edge import KernelSpec, dispatch_kernel_spec
from django_spec_rest.views.utils import view_call_context


def dispatch_selector_for_spec(view: Any, spec: KernelSelectorSpec) -> Any:
    """The value a kernel selector spec answers for a DRF view's request.

    A RETRIEVE that resolved nothing raises ``NotFound``, unless the spec sets
    ``allow_none=True`` (then ``None``, and the retrieve views render 200 + JSON
    ``null``). ``SelectorKind.LIST`` returns the shaped queryset. The query views,
    which present the result, take the whole of it from ``dispatch_kernel_selector``.
    """
    return dispatch_kernel_selector(view, spec).value


def dispatch_kernel_selector(view: Any, spec: KernelSpec) -> DispatchResult:
    """Run a kernel ``spec`` for a selector view's request, the result whole.

    A selector spec, which ``as_view()`` holds every selector view to.

    The kernel's own ``dispatch`` reads the query string and the declared route
    captures (``dispatch_kernel_spec``); a RETRIEVE that found nothing raises
    ``NotFound``, so what comes back is always presentable: a row, a set, or
    ``None`` under ``allow_none``. The result rather than its value, so the
    query views present it through the spec's own presenter, with the context
    dispatch built for it.

    **The query string it reads is the spec's alone**: the keys DRF's own
    pagination, filter backends, versioning and format suffix read on the view
    are taken off it first (``kernel_query``), so ``?page=2`` turns the page
    rather than reaching the kernel's closed argument set as an unknown
    argument (test_selector_list_view's
    test_a_drf_key_is_read_by_drf_and_never_by_the_kernel).

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
        query=kernel_query(view, cast(KernelSelectorSpec, spec), view.request),
    )
    if found.kind == "not_found":
        raise NotFound()
    return found


def present_kernel_selection(
    view: Any, spec: KernelSelectorSpec, result: DispatchResult, rows: Any, *, many: bool
) -> Any:
    """``rows`` of a kernel selector ``result`` as the response body: the spec's, or the view's.

    The spec's presenter is handed ``rows`` inside the result dispatch built,
    so it renders what is served (a page's rows) with the call's context. A
    spec declaring neither presenter nor affordances is rendered by the view's
    ``get_serializer``, as DRF renders a queryset; one declaring affordances
    with no presenter is refused by ``present`` rather than having them
    dropped. Shared by the viewset mixins and ``@selector_action``.
    """
    # One arc to coverage, so each disjunct is named: a presenter by
    # test_service_viewset's test_list_is_presented_by_the_spec, affordances
    # with none by test_selector_viewset's
    # test_affordances_with_no_presenter_are_refused_rather_than_dropped.
    if spec.presenter is not None or spec.affordances is not None:
        return present(spec, dataclasses.replace(result, value=rows))
    return view.get_serializer(rows, many=many).data


def present_kernel_list(view: Any, spec: KernelSelectorSpec, *, filtered: bool) -> tuple[Any, bool]:
    """Dispatch a kernel LIST spec for ``view`` and present it: the body, and whether it is a page.

    DRF's ``list`` steps in DRF's order on the set the dispatch read: the
    view's filter backends where ``filtered`` (a viewset's ``list``; a custom
    ``@selector_action`` applies none, as DRF's ``@action`` leaves that to its
    handler), then its paginator where it has one (DRF's bare ``ViewSet`` has
    none), then ``present_kernel_selection``. The caller wraps the body,
    through ``get_paginated_response`` for a page.
    """
    result = dispatch_kernel_selector(view, spec)
    rows = view.filter_queryset(result.value) if filtered else result.value
    paginate = getattr(view, "paginate_queryset", None)
    page = None if paginate is None else paginate(rows)
    served = rows if page is None else page
    return present_kernel_selection(view, spec, result, served, many=True), page is not None


def present_kernel_row(view: Any, spec: KernelSelectorSpec) -> tuple[Any, Any]:
    """Dispatch a kernel RETRIEVE spec for ``view``: the row found, and its body.

    The row is ``None`` only under ``allow_none`` (any other miss raised
    ``NotFound`` inside ``dispatch_kernel_selector``), and then nothing is
    presented: the caller answers JSON ``null``.
    """
    result = dispatch_kernel_selector(view, spec)
    if result.value is None:
        return None, None
    return result.value, present_kernel_selection(view, spec, result, result.value, many=False)


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
    # Two conjuncts, one branch arc: ``cached[0]() is spec`` refuses an entry a
    # reused ``id`` left under another spec (held by
    # test_a_stale_entry_under_a_live_spec_s_id_is_not_its_twin), and the weakref
    # callback below is what normally keeps such an entry from existing
    # (test_a_dead_spec_leaves_no_twin_behind).
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
    reading no such key, names none, and nor does a non-string value (a number)
    (test_drf_query_keys, its ``_OwnFilter`` row holding the blank and the number). A view-level ``DjangoFilterBackend`` reading a
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
    readers = [getattr(view, "paginator", None), *getattr(view, "filter_backends", ())]
    # ``version_param`` sits on ``BaseVersioning``, so URL path, header, namespace
    # and host name versioning all report it without reading it: only the
    # query-parameter class does, and an undeclared ``?version`` on the others
    # stays the kernel's to refuse. ``isinstance(.., type)`` keeps a view with no
    # versioning (``None``) out of ``issubclass``; both conjuncts are held by
    # test_drf_query_keys (its ``_View()`` row and its non-query versioning rows).
    versioning = getattr(view, "versioning_class", None)
    if isinstance(versioning, type) and issubclass(versioning, QueryParameterVersioning):
        readers.append(versioning)
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
