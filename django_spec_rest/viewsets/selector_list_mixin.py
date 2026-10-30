"""Action-keyed list selector override on top of ``ListModelMixin``."""

from __future__ import annotations

from typing import Any

from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from rest_framework.mixins import ListModelMixin
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.selectors.utils import dispatch_selector_for_spec, present_kernel_list
from django_spec_rest.views.utils import list_with_affordances
from django_spec_rest.viewsets.utils import (
    _ActionSpecsMixin,
    _SelectorHooks,
    resolve_action_selector_spec,
)


class SelectorListMixin(ListModelMixin, _SelectorHooks, _ActionSpecsMixin):
    """Compose with ``GenericViewSet``.

    When ``action_specs["list"]`` is a
    [`SelectorSpec`][django_spec_rest.types.selector_spec.SelectorSpec] with
    a non-``None`` ``selector``, ``get_queryset()`` invokes it instead of
    returning the configured ``queryset``. The rest of DRF's list flow —
    filter backends, pagination, serialization — is unchanged.

    ``action_specs["list"] = SelectorSpec(selector=None)`` or an absent
    ``"list"`` key both fall through to DRF's default ``get_queryset()``.
    Any other entry type raises
    ``ImproperlyConfigured``.

    A kernel ``SelectorSpec`` under ``"list"`` runs through the kernel's own
    ``dispatch``, as on ``SelectorListView``: the view's filter backends and
    paginator apply to the set it read, and the spec's ``presenter`` renders
    the rows served, with the affordance answers it declares; a spec declaring
    neither is rendered by the view's serializer. ``get_queryset()`` still
    answers the spec's set to whatever else asks it.
    """

    # Provided at runtime by ``GenericViewSet`` / ``GenericAPIView``.
    request: Any
    kwargs: dict[str, Any]

    def paginate_queryset(self, queryset: Any) -> Any:
        # Stash the materialized page (or the full queryset when pagination
        # is off) so a SelectorSpec's output context provider can read it via
        # the ``page`` extra. See ``_ActionSpecsMixin.get_serializer_context``.
        page = super().paginate_queryset(queryset)  # ty: ignore[unresolved-attribute]
        self._resolved_page = page if page is not None else queryset
        return page

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        spec = resolve_action_selector_spec(self.action_specs, "list")
        if isinstance(spec, KernelSelectorSpec):
            # Dispatched once, here, rather than through ``get_queryset()``:
            # the result dispatch built is what the spec's presenter renders
            # (test_service_viewset's test_a_list_is_dispatched_once).
            data, paginated = present_kernel_list(self, spec, filtered=True)
            return self.get_paginated_response(data) if paginated else Response(data)  # ty: ignore[unresolved-attribute]
        if spec is None or spec.affordances is None:
            return super().list(request, *args, **kwargs)
        return list_with_affordances(self, spec)

    def get_queryset(self) -> Any:
        spec = resolve_action_selector_spec(self.action_specs, "list")
        if spec is None:
            return super().get_queryset()
        return dispatch_selector_for_spec(self, spec)
