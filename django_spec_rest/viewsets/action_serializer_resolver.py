from __future__ import annotations

from typing import Any

from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from rest_framework.serializers import BaseSerializer

from django_spec_rest.types.discriminated_action import DiscriminatedAction
from django_spec_rest.views.mutation.kernel_input_serializer_class import (
    kernel_input_serializer_class,
)
from django_spec_rest.viewsets.utils import _ActionSpecsMixin, resolve_action_spec


class ActionSerializerResolver(_ActionSpecsMixin):
    """Resolve ``get_serializer_class()`` from ``action_specs``.

    A kernel
    [`ServiceSpec`][django_service_specs.specs.service_spec.ServiceSpec] answers
    with its input serializer where the view sets no ``serializer_class``. Every
    other case falls back to DRF's ``serializer_class``, raising the usual
    ``AssertionError`` when none is set.

    Example:

        class InvoiceViewSet(ActionSerializerResolver, GenericViewSet):
            action_specs = {
                "create": ServiceSpec(service=create_invoice),
            }
    """

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        # Answers the input serializer where no view sets one (``kernel_input_serializer_class``).
        spec = resolve_action_spec(self, self.action)
        if isinstance(spec, DiscriminatedAction):
            spec = next(iter(spec.specs.values()))
        if isinstance(spec, KernelServiceSpec) and getattr(self, "serializer_class", None) is None:
            return kernel_input_serializer_class(spec)
        return super().get_serializer_class()  # ty: ignore[unresolved-attribute]
