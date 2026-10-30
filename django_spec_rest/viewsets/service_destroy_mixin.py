"""``destroy`` action backed by a service callable."""

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


class ServiceDestroyMixin(MutationFlowMixin, _ActionSpecsMixin):
    """Provides the ``destroy`` action.

    The row is the spec's own target selector's, never ``get_object()``'s. Reads its config from
    ``action_specs["destroy"]``; when that key is absent the action raises
    ``MethodNotAllowed``. A non-``ServiceSpec``
    entry raises ``ImproperlyConfigured``.
    """

    # Provided at runtime by ``GenericAPIView`` / ``GenericViewSet``.
    get_object: Callable[..., Any]

    @dispatches_action_specs
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        spec = resolve_action_service_spec(self.action_specs, "destroy", "DELETE")
        return self._run_mutation(
            request,
            spec,
            instance=resolve_mutation_instance(self, spec),
            default_status=drf_status.HTTP_204_NO_CONTENT,
        )
