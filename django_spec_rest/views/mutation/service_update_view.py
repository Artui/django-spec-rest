"""Generic update endpoint backed by a user-defined service callable."""

from __future__ import annotations

from typing import Any, ClassVar

from django_service_specs.specs.service_spec import ServiceSpec
from rest_framework import status as drf_status
from rest_framework.generics import GenericAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from django_spec_rest.views.mutation.kernel_input_serializer_class import (
    standalone_form_serializer_class,
)
from django_spec_rest.views.mutation.mutation_flow_mixin import MutationFlowMixin
from django_spec_rest.views.mutation.utils import resolve_mutation_instance
from django_spec_rest.views.spec_options import spec_options
from django_spec_rest.views.spec_validation import validate_mutation_view_spec


class ServiceUpdateView(MutationFlowMixin, GenericAPIView):
    """``PUT`` / ``PATCH`` endpoint that runs a service callable.

    The instance to update is resolved via ``spec.instance_selector_spec`` — no
    ``queryset`` / ``lookup_field`` required on the subclass. A spec never falls
    back to DRF's ``get_object()``, its target being its own lookup's, so
    ``as_view()`` refuses one that declares neither a target selector nor ``many``.

    Configure by setting ``spec`` to a kernel ``ServiceSpec``. The view's
    ``success_status`` defaults to ``200 OK`` when unset. Both verbs share the one spec,
    so a forced ``spec.partial`` applies to PUT *and* PATCH — set ``http_method_names =
    ["patch"]`` for a PATCH-only endpoint."""

    spec: ClassVar[ServiceSpec | None] = None

    @classmethod
    def as_view(cls, **initkwargs: Any) -> Any:
        validate_mutation_view_spec(cls, has_instance=True)
        return super().as_view(**initkwargs)

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        # Only DRF's browsable renderer asks a spec-only kernel view, for the
        # forms it draws on every HTML page (``standalone_form_serializer_class``).
        return standalone_form_serializer_class(self) or super().get_serializer_class()

    def options(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # The spec describes the route, never DRF's probe of ``get_object()``
        # and ``serializer_class`` (``spec_options``).
        if self.spec is not None:
            return spec_options(self, request, {"PUT": self.spec})
        return super().options(request, *args, **kwargs)

    def put(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._run(request, partial=False)

    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._run(request, partial=True)

    def _run(self, request: Request, *, partial: bool) -> Response:
        spec: ServiceSpec | None = self.spec
        if spec is None:
            raise NotImplementedError(
                f"{type(self).__name__} requires a `spec` (ServiceSpec) attribute."
            )
        return self._run_mutation(
            request,
            spec,
            instance=resolve_mutation_instance(self, spec),
            default_status=drf_status.HTTP_200_OK,
            render_instance_on_none=True,
            partial=partial,
        )
