from __future__ import annotations

from typing import Any

from rest_framework.exceptions import MethodNotAllowed
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.selectors.utils import dispatch_selector_for_spec, present_kernel_row
from django_spec_rest.views.utils import _JsonNullResponse
from django_spec_rest.viewsets.utils import (
    _ActionSpecsMixin,
    resolve_action_selector_spec,
)


class SelectorRetrieveMixin(RetrieveModelMixin, _ActionSpecsMixin):
    """Compose with ``GenericViewSet``.

    An absent ``"retrieve"`` key falls through to DRF's default ``get_object()``
    where the viewset has rows and a serializer for it, and otherwise answers 405,
    leaving ``Allow`` and the schema (test_a_read_with_no_fallback). Any entry that is not a kernel
    [`SelectorSpec`][django_service_specs.specs.selector_spec.SelectorSpec]
    raises ``ImproperlyConfigured``.

    A kernel ``SelectorSpec`` under ``"retrieve"`` runs through the kernel's
    own ``dispatch``, as on ``SelectorRetrieveView``: the view's object
    permission is asked of the row inside it, and the spec's ``presenter``
    renders the row, or the view's serializer where the spec declares neither
    presenter nor affordances. A miss is a 404, or JSON ``null`` under
    ``allow_none``. A kernel write spec never asks ``get_object()``: its target
    is its own selector's.
    """

    request: Any
    kwargs: dict[str, Any]

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        spec = resolve_action_selector_spec(self.action_specs, "retrieve")
        if spec is None:
            if self._has_no_fallback("retrieve"):
                raise MethodNotAllowed(self.request.method)
            return super().retrieve(request, *args, **kwargs)
        row, data = present_kernel_row(self, spec)
        return _JsonNullResponse() if row is None else Response(data)

    def get_object(self) -> Any:
        """Resolve the target row through the retrieve selector, if one is wired."""
        spec = resolve_action_selector_spec(self.action_specs, "retrieve")
        return super().get_object() if spec is None else dispatch_selector_for_spec(self, spec)  # ty: ignore[unresolved-attribute]
