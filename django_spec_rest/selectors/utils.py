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
from django_spec_rest.views.utils import view_call_context, view_pool_seeds


def dispatch_selector_for_spec(view: Any, spec: KernelSelectorSpec) -> Any:
    """The value a kernel selector spec answers for a DRF view's request."""
    return dispatch_kernel_selector(view, spec).value


def dispatch_kernel_selector(view: Any, spec: KernelSpec) -> DispatchResult:
    """Run a kernel ``spec`` for a selector view's request, the result whole."""
    found = dispatch_kernel_spec(
        _viewed(spec),
        view=view,
        request=view.request,
        call_context=view_call_context(view, view.request),
        query=kernel_query(view, cast(KernelSelectorSpec, spec), view.request),
        pool_seeds=view_pool_seeds(view),
    )
    if found.kind == "not_found":
        raise NotFound()
    return found


def present_kernel_selection(
    view: Any, spec: KernelSelectorSpec, result: DispatchResult, rows: Any, *, many: bool
) -> Any:
    """``rows`` of a kernel selector ``result`` as the response body: the spec's, or the view's."""
    if spec.presenter is not None or spec.affordances is not None:
        return present(spec, dataclasses.replace(result, value=rows))
    return view.get_serializer(rows, many=many).data


# The attribute ``dispatch_list_once`` keeps its dispatch in, on the view.
_LIST_DISPATCH = "_spec_rest_list_dispatch"


def dispatch_list_once(view: Any, spec: KernelSelectorSpec) -> DispatchResult:
    """The one dispatch of a ``list``'s spec for ``view``'s request, kept on the view."""
    kept: tuple[Any, DispatchResult] | None = getattr(view, _LIST_DISPATCH, None)
    if kept is not None and kept[0] is view.request:
        return kept[1]
    result = dispatch_kernel_selector(view, spec)
    setattr(view, _LIST_DISPATCH, (view.request, result))
    return result


def present_kernel_list(
    view: Any, spec: KernelSelectorSpec, result: DispatchResult, *, filtered: bool
) -> tuple[Any, bool]:
    """Present a kernel LIST spec's ``result`` for ``view``: the body, and whether it is a page."""
    rows = view.filter_queryset(result.value) if filtered else result.value
    paginate = getattr(view, "paginate_queryset", None)
    page = None if paginate is None else paginate(rows)
    served = rows if page is None else page
    return present_kernel_selection(view, spec, result, served, many=True), page is not None


def present_kernel_row(view: Any, spec: KernelSelectorSpec) -> tuple[Any, Any]:
    """Dispatch a kernel RETRIEVE spec for ``view``: the row found, and its body."""
    result = dispatch_kernel_selector(view, spec)
    if result.value is None:
        return None, None
    return result.value, present_kernel_selection(view, spec, result, result.value, many=False)


class _ViewObjectPermission(PermissionCheck):
    """The view's own ``check_object_permissions``, as a kernel check."""

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
        # The kernel hands every check declaring ``call_context`` the call's dict, so ``None`` is a caller asking outside a dispatch, with no view to ask: refused, never allowed unasked (test_the_view_s_check_asked_with_no_call_context_refuses).
        if call_context is None:
            return False
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
    """``spec`` with the view's object permission first among its ``permissions``."""
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
    """The query-string keys DRF's own machinery reads on ``view``, not the spec."""
    keys: set[str] = set()
    if api_settings.URL_FORMAT_OVERRIDE:
        keys.add(api_settings.URL_FORMAT_OVERRIDE)
    readers = [getattr(view, "paginator", None), *getattr(view, "filter_backends", ())]
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
    """``request.query_params`` without the keys DRF reads on ``view``, for the kernel."""
    declared = spec.parameters()
    query = request.query_params.copy()
    for key in drf_query_keys(view):
        if declared.get(key) is None:
            query.pop(key, None)
    return query
