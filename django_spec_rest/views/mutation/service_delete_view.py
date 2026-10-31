"""Generic delete endpoint backed by a user-defined service callable."""

from __future__ import annotations

from typing import Any, ClassVar

from django_service_specs.specs.service_spec import ServiceSpec
from rest_framework import status as drf_status
from rest_framework.generics import GenericAPIView
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.views.mutation.mutation_flow_mixin import MutationFlowMixin
from django_spec_rest.views.mutation.utils import resolve_mutation_instance
from django_spec_rest.views.spec_validation import validate_mutation_view_spec


class ServiceDeleteView(MutationFlowMixin, GenericAPIView):
    """``DELETE`` endpoint that runs a service callable.

    The instance to delete is resolved via ``spec.instance_selector_spec`` — no
    ``queryset`` / ``lookup_field`` required on the subclass. A spec never falls
    back to DRF's ``get_object()``, its target being its own lookup's, so
    ``as_view()`` refuses one that declares neither a target selector nor ``many``.

    Configure by setting ``spec`` to a kernel ``ServiceSpec``. Its validator is
    optional (for delete-with-payload patterns such as a deletion reason); the
    view's ``success_status`` defaults to ``204 No Content``; set
    ``output_selector_spec`` with a presenter on the spec to render a body
    instead."""

    spec: ClassVar[ServiceSpec | None] = None

    @classmethod
    def as_view(cls, **initkwargs: Any) -> Any:
        validate_mutation_view_spec(cls, has_instance=True)
        return super().as_view(**initkwargs)

    def delete(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        spec: ServiceSpec | None = self.spec
        if spec is None:
            raise NotImplementedError(
                f"{type(self).__name__} requires a `spec` (ServiceSpec) attribute."
            )
        return self._run_mutation(
            request,
            spec,
            instance=resolve_mutation_instance(self, spec),
            default_status=drf_status.HTTP_204_NO_CONTENT,
        )
