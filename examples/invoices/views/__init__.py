"""Kernel specs, served on a viewset and on a standalone view.

Every spec is the kernel's own ``ServiceSpec`` or ``SelectorSpec``. DRF enters
through the seats: a ``SerializerValidator`` validates a body with a DRF
serializer, a ``SerializerPresenter`` renders with one, and a
``DRFPermissionCheck`` asks DRF permission classes. The same spec runs off HTTP
through the kernel's ``dispatch``, which is how ``SEND_SPEC`` is reached in the
tests without a request.
"""

from __future__ import annotations

from typing import Any

from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework.permissions import IsAuthenticated

from django_spec_rest import SelectorListView, ServiceViewSet, service_action
from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from invoices.selectors import InvoiceFilter, get_invoice, list_invoices, sent_invoices
from invoices.serializers import InvoiceInput, InvoiceSerializer
from invoices.services import create_invoice, send_invoice, update_invoice

OPEN = (Unrestricted(),)
PRESENTER = SerializerPresenter(InvoiceSerializer)

# One row by ``pk``. On a detail route the edge reads ``pk`` from the URL;
# off HTTP the caller passes it as an argument. A nested selector declares no
# ``permissions``: the spec being dispatched is what authorizes, and
# ``as_view()`` refuses a nested selector that declares them.
INVOICE_LOOKUP = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=get_invoice,
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
)

LIST_SPEC = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=list_invoices,
    filter_set=InvoiceFilter,
    permissions=OPEN,
    presenter=PRESENTER,
)

RETRIEVE_SPEC = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=get_invoice,
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
    permissions=OPEN,
    presenter=PRESENTER,
)

CREATE_SPEC = ServiceSpec(
    service=create_invoice,
    validator=SerializerValidator(InvoiceInput),
    permissions=OPEN,
    presenter=PRESENTER,
)

# A write's target is its own selector's, never ``get_object()``'s.
UPDATE_SPEC = ServiceSpec(
    service=update_invoice,
    validator=SerializerValidator(InvoiceInput),
    instance_selector_spec=INVOICE_LOOKUP,
    permissions=OPEN,
    presenter=PRESENTER,
)

# Asked of DRF's ``IsAuthenticated`` over HTTP and through the kernel's own
# ``dispatch`` alike.
SEND_SPEC = ServiceSpec(
    service=send_invoice,
    instance_selector_spec=INVOICE_LOOKUP,
    permissions=(DRFPermissionCheck([IsAuthenticated]),),
    presenter=PRESENTER,
)

SENT_SPEC = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=sent_invoices,
    permissions=OPEN,
    presenter=PRESENTER,
)


class InvoiceViewSet(ServiceViewSet):
    """``/invoices/`` and ``/invoices/<pk>/``, plus ``POST /invoices/<pk>/send/``.

    No ``"destroy"`` spec: ``DELETE`` answers 405 and the detail route's
    ``Allow`` header leaves it out. ``PATCH`` falls back to the ``"update"``
    spec, validated partially.
    """

    action_specs = {
        "list": LIST_SPEC,
        "retrieve": RETRIEVE_SPEC,
        "create": CREATE_SPEC,
        "update": UPDATE_SPEC,
    }

    @service_action(SEND_SPEC, detail=True, methods=["post"])
    def send(self, request: Any, pk: Any = None) -> None:
        """Mark a draft as sent."""


class SentInvoiceListView(SelectorListView):
    """``GET /sent-invoices/``: one selector spec on a standalone view."""

    spec = SENT_SPEC
