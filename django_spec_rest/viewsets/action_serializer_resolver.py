"""Per-action serializer dispatch for ViewSets driven by ``action_specs``."""

from __future__ import annotations

from typing import Any

from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from rest_framework.serializers import BaseSerializer

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
        # A kernel service spec answers with its input serializer where the
        # view sets none: only DRF's browsable renderer asks, building a form
        # per write method under the action that method routes to, and a
        # spec-only kernel viewset ended every HTML page in DRF's assertion
        # (``kernel_input_serializer_class``). Read through
        # ``resolve_action_spec``, so a spec ``@service_action`` stamped is
        # found too. Each condition is held by a test of test_spec_options: the
        # kernel spec by the service-viewset rows of
        # test_options_rendered_as_html_answers (a selector spec falls through
        # by test_a_kernel_list_without_a_presenter_still_needs_a_serializer_class),
        # the missing ``serializer_class`` by the service-viewset row of
        # test_a_kernel_views_own_serializer_class_draws_its_forms.
        spec = resolve_action_spec(self, self.action)
        if isinstance(spec, KernelServiceSpec) and getattr(self, "serializer_class", None) is None:
            return kernel_input_serializer_class(spec)
        return super().get_serializer_class()  # ty: ignore[unresolved-attribute]
