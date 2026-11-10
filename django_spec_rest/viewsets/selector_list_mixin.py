from __future__ import annotations

from typing import Any

from rest_framework.exceptions import MethodNotAllowed
from rest_framework.mixins import ListModelMixin
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.selectors.utils import dispatch_list_once, present_kernel_list
from django_spec_rest.viewsets.utils import (
    _ActionSpecsMixin,
    resolve_action_selector_spec,
)


class SelectorListMixin(ListModelMixin, _ActionSpecsMixin):
    """Compose with ``GenericViewSet``.

    An absent ``"list"`` key falls through to DRF's default ``get_queryset()``
    where the viewset has rows and a serializer for it, and otherwise answers 405,
    leaving ``Allow`` and the schema (test_a_read_with_no_fallback). Any entry that is not a kernel
    [`SelectorSpec`][django_service_specs.specs.selector_spec.SelectorSpec]
    raises ``ImproperlyConfigured``.

    A kernel ``SelectorSpec`` under ``"list"`` runs through the kernel's own
    ``dispatch``, as on ``SelectorListView``: the view's filter backends and
    paginator apply to the set it read, and the spec's ``presenter`` renders
    the rows served, with the affordance answers it declares; a spec declaring
    neither is rendered by the view's serializer.

    ``get_queryset()`` answers the list spec's set on ``list`` alone, from the
    one dispatch ``list`` presents. On every other action it is DRF's own, the
    viewset's ``queryset``: DRF's ``DjangoModelPermissions`` asks it on every
    action for the model it checks, and a ``retrieve`` or a ``PATCH`` beside a
    list spec answers as its own spec says, never the list's refusal
    (test_selector_list_mixin).
    """

    action: str | None
    request: Any
    kwargs: dict[str, Any]

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        spec = resolve_action_selector_spec(self.action_specs, "list")
        if spec is not None:
            # The dispatch a permission class's ``get_queryset()`` made, if one asked first, never the set ``get_queryset()`` answers: a subclass overriding it does not choose the rows a spec serves.
            result = dispatch_list_once(self, spec)
            data, paginated = present_kernel_list(self, spec, result, filtered=True)
            return self.get_paginated_response(data) if paginated else Response(data)  # ty: ignore[unresolved-attribute]
        if self._has_no_fallback("list"):
            raise MethodNotAllowed(self.request.method)
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> Any:
        spec = resolve_action_selector_spec(self.action_specs, "list")
        if spec is None or self.action != "list":
            return super().get_queryset()  # ty: ignore[unresolved-attribute]
        return dispatch_list_once(self, spec).value
