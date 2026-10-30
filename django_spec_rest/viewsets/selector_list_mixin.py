"""Action-keyed list selector override on top of ``ListModelMixin``."""

from __future__ import annotations

from typing import Any

from rest_framework.mixins import ListModelMixin
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.selectors.utils import dispatch_selector_for_spec, present_kernel_list
from django_spec_rest.viewsets.utils import (
    _ActionSpecsMixin,
    _SelectorHooks,
    resolve_action_selector_spec,
)


class SelectorListMixin(ListModelMixin, _SelectorHooks, _ActionSpecsMixin):
    """Compose with ``GenericViewSet``.

    An absent ``"list"`` key falls through to DRF's default ``get_queryset()``.
    Any entry that is not a kernel
    [`SelectorSpec`][django_service_specs.specs.selector_spec.SelectorSpec]
    raises ``ImproperlyConfigured``.

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

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        spec = resolve_action_selector_spec(self.action_specs, "list")
        if spec is not None:
            # Dispatched once, here, rather than through ``get_queryset()``:
            # the result dispatch built is what the spec's presenter renders
            # (test_service_viewset's test_a_list_is_dispatched_once).
            data, paginated = present_kernel_list(self, spec, filtered=True)
            return self.get_paginated_response(data) if paginated else Response(data)  # ty: ignore[unresolved-attribute]
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> Any:
        spec = resolve_action_selector_spec(self.action_specs, "list")
        if spec is None:
            return super().get_queryset()  # ty: ignore[unresolved-attribute]
        return dispatch_selector_for_spec(self, spec)
