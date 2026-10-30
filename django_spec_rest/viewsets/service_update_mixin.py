"""``update`` and ``partial_update`` actions backed by a service callable."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rest_framework import status as drf_status
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.views.mutation.mutation_flow_mixin import MutationFlowMixin
from django_spec_rest.views.mutation.utils import resolve_mutation_instance
from django_spec_rest.viewsets.utils import (
    _ActionSpecsMixin,
    dispatches_action_specs,
    resolve_action_service_spec,
)


class ServiceUpdateMixin(MutationFlowMixin, _ActionSpecsMixin):
    """Provides ``update`` (``PUT``) and ``partial_update`` (``PATCH``) actions.

    The row is the spec's own target selector's, never ``get_object()``'s.
    ``PUT`` reads its config from
    ``action_specs["update"]``; ``PATCH`` reads ``action_specs["partial_update"]``
    first and falls back to ``"update"`` — defining *only*
    ``"partial_update"`` yields a PATCH-only endpoint (PUT raises
    ``MethodNotAllowed``). When neither key
    resolves, both actions raise
    ``MethodNotAllowed``. A non-``ServiceSpec``
    entry raises ``ImproperlyConfigured``.
    """

    # Provided at runtime by ``GenericAPIView`` / ``GenericViewSet``.
    get_object: Callable[..., Any]

    @dispatches_action_specs
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._update(request, partial=False)

    @dispatches_action_specs
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._update(request, partial=True)

    def _update(self, request: Request, *, partial: bool) -> Response:
        spec = resolve_action_service_spec(
            self.action_specs,
            "partial_update" if partial else "update",
            "PATCH" if partial else "PUT",
        )
        return self._run_mutation(
            request,
            spec,
            instance=resolve_mutation_instance(self, spec),
            default_status=drf_status.HTTP_200_OK,
            render_instance_on_none=True,
            partial=partial,
        )
