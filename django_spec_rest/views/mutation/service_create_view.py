"""Generic create endpoint backed by a user-defined service callable."""

from __future__ import annotations

from typing import Any, ClassVar

from rest_framework import status as drf_status
from rest_framework.generics import GenericAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from django_spec_rest.dispatch.kernel_edge import runs_on_kernel
from django_spec_rest.types.service_spec import ServiceSpec
from django_spec_rest.views.mutation.kernel_input_serializer_class import (
    standalone_form_serializer_class,
)
from django_spec_rest.views.mutation.mutation_flow_mixin import MutationFlowMixin
from django_spec_rest.views.spec_options import spec_options
from django_spec_rest.views.spec_validation import validate_mutation_view_spec


class ServiceCreateView(MutationFlowMixin, GenericAPIView):
    """``POST`` endpoint that runs a service callable to create a resource.

    Configure by setting ``spec`` to a
    [`ServiceSpec`][django_spec_rest.types.service_spec.ServiceSpec]. The spec's
    ``success_status`` defaults to ``201 Created`` when unset."""

    spec: ClassVar[ServiceSpec | None] = None

    @classmethod
    def as_view(cls, **initkwargs: Any) -> Any:
        validate_mutation_view_spec(cls, has_instance=False)
        return super().as_view(**initkwargs)

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        # Only DRF's browsable renderer asks a spec-only kernel view, for the
        # forms it draws on every HTML page (``standalone_form_serializer_class``).
        return standalone_form_serializer_class(self) or super().get_serializer_class()

    def options(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # A kernel spec is described from the spec, never from DRF's probe of
        # ``get_object()`` and ``serializer_class`` (``spec_options``); a drfs
        # spec keeps DRF's own answer until that path goes.
        if runs_on_kernel(self.spec):
            return spec_options(self, request, {"POST": self.spec})
        return super().options(request, *args, **kwargs)

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        spec: ServiceSpec | None = self.spec
        if spec is None:
            raise NotImplementedError(
                f"{type(self).__name__} requires a `spec` (ServiceSpec) attribute."
            )
        return self._run_mutation(
            request,
            spec,
            instance=None,
            default_status=drf_status.HTTP_201_CREATED,
        )
