"""Action-keyed retrieve selector override on top of ``RetrieveModelMixin``."""

from __future__ import annotations

from typing import Any

from rest_framework.mixins import RetrieveModelMixin
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.selectors.utils import dispatch_selector_for_spec, present_kernel_row
from django_spec_rest.views.utils import _JsonNullResponse
from django_spec_rest.viewsets.utils import (
    _ActionSpecsMixin,
    _SelectorHooks,
    resolve_action_selector_spec,
)


class SelectorRetrieveMixin(RetrieveModelMixin, _SelectorHooks, _ActionSpecsMixin):
    """Compose with ``GenericViewSet``.

    An absent ``"retrieve"`` key falls through to DRF's default ``get_object()``.
    Any entry that is not a kernel
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

    # Provided at runtime by ``GenericViewSet`` / ``GenericAPIView``.
    request: Any
    kwargs: dict[str, Any]

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        spec = resolve_action_selector_spec(self.action_specs, "retrieve")
        if spec is None:
            return super().retrieve(request, *args, **kwargs)
        row, data = present_kernel_row(self, spec)
        return _JsonNullResponse() if row is None else Response(data)

    def get_object(self) -> Any:
        """Resolve the target row through the retrieve selector, if one is wired.

        **``filter_backends`` do not apply here.** DRF runs
        ``filter_queryset()`` inside its own ``get_object()``, so taking that
        method over — as this mixin does, and as any hand-written
        ``get_object()`` override does — is what drops them. A tenant-scoping
        backend listed in ``DEFAULT_FILTER_BACKENDS`` therefore narrows the
        sibling ``list`` action and *not* this lookup, which is what makes the
        gap easy to miss. Scope the selector's own queryset, or declare the
        rule as ``SelectorSpec.filter_set`` — the sanctioned seam, applied by
        the dispatcher on both paths.
        """
        spec = resolve_action_selector_spec(self.action_specs, "retrieve")
        return super().get_object() if spec is None else dispatch_selector_for_spec(self, spec)  # ty: ignore[unresolved-attribute]
