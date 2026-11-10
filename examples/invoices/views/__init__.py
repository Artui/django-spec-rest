"""Kernel specs, served on a viewset and on a standalone view.

Every spec is the kernel's own ``ServiceSpec`` or ``SelectorSpec``. DRF enters
through the seats: a ``SerializerValidator`` validates a body with a DRF
serializer, a ``SerializerPresenter`` renders with one, and a
``DRFPermissionCheck`` asks DRF permission classes. The same spec runs off HTTP
through the kernel's ``dispatch``, which is how ``SEND_SPEC`` is reached in the
tests without a request, handed the same ``SEEDS`` the viewset registers.
"""

from __future__ import annotations

from typing import Any

from django_service_specs import (
    DEFAULT_POOL_SEEDS,
    Affordance,
    Output,
    OutputField,
    Parameter,
    Parameters,
    PermissionCheck,
    Presenter,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework.authentication import BasicAuthentication
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import (
    DiscriminatedAction,
    SelectorListView,
    ServiceCreateMixin,
    ServiceCreateView,
    ServiceUpdateView,
    ServiceViewSet,
    service_action,
)
from django_spec_rest.openapi import (
    SERVICE_ERROR_METADATA_KEY,
    NotAuthenticatedSerializer,
    PermissionDeniedSerializer,
    ServiceConflictSerializer,
)
from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from invoices.models import Invoice
from invoices.selectors import InvoiceFilter, get_invoice, list_invoices, sent_invoices
from invoices.serializers import (
    BlankInvoiceInput,
    InvoiceInput,
    InvoiceSerializer,
    ReceiptInput,
)
from invoices.services import (
    create_blank_invoice,
    create_invoice,
    send_invoice,
    sending_paused,
    set_receipt,
    update_invoice,
)

OPEN = (Unrestricted(),)
PRESENTER = SerializerPresenter(InvoiceSerializer)

# What an invoice has reached: nothing yet while it is a draft.
STAGES = (("billed", "Billed"), ("settled", "Settled"))


class InvoiceSummaryPresenter(Presenter):
    """A presenter that is no serializer: the document's response is the kernel's ``output_schema``.

    ``stage`` is a labelled choice that admits null, the shape the kernel writes
    as JSON Schema (a type list, a ``oneOf`` of constants). Under OpenAPI 3.0,
    drf-spectacular's default, the package writes it as ``nullable`` and an
    ``enum``; ``OpenAPISchemaTests`` validates the project's default document.
    """

    def output(self) -> Output:
        return Output(
            (
                OutputField("customer", "string"),
                OutputField("status", "string", choices=Invoice.STATUS_CHOICES),
                OutputField("stage", "string", choices=STAGES, nullable=True),
            )
        )

    def present(self, value: Invoice) -> dict[str, Any]:
        stage = {
            Invoice.STATUS_DRAFT: None,
            Invoice.STATUS_SENT: "billed",
            Invoice.STATUS_PAID: "settled",
            Invoice.STATUS_VOID: "settled",
        }[value.status]
        return {"customer": value.customer, "status": value.status, "stage": stage}


# The seeds the viewset registers (``InvoiceViewSet.pool_seeds``). A callable
# declaring ``sending_paused`` is handed its value. ``SEND_SPEC`` is served by
# a ``@service_action``, whose seeds ``InvoiceViewSet.as_view()`` checks as it
# checks ``action_specs``: a viewset not registering it is refused at mount,
# naming the seed.
SEEDS = DEFAULT_POOL_SEEDS.extend(sending_paused=sending_paused)

# One row by ``pk``. On a detail route the edge reads ``pk`` from the URL;
# off HTTP the caller passes it as an argument. A nested selector declares no
# ``permissions``: the spec being dispatched is what authorizes, and the kernel
# refuses a nested selector that declares them when the ServiceSpec is built.
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

# The second variant of ``/intake/``: a body of its own, so the route's request
# is documented as an ``anyOf`` of the two.
BLANK_SPEC = ServiceSpec(
    service=create_blank_invoice,
    validator=SerializerValidator(BlankInvoiceInput),
    permissions=OPEN,
    presenter=PRESENTER,
)


def invoice_intake(*, data: Any) -> str:
    """Choose the variant from the body: a request naming an amount is a full draft."""
    return "draft" if "amount_cents" in data else "blank"


# One URL, two specs: the request chooses. Each variant is asked what a plain
# ``create`` entry is asked, and the chosen one's own checks decide.
INTAKE = DiscriminatedAction(
    discriminator=invoice_intake, specs={"draft": CREATE_SPEC, "blank": BLANK_SPEC}
)

# A write's target is its own selector's, never ``get_object()``'s.
UPDATE_SPEC = ServiceSpec(
    service=update_invoice,
    validator=SerializerValidator(InvoiceInput),
    instance_selector_spec=INVOICE_LOOKUP,
    permissions=OPEN,
    presenter=PRESENTER,
)

# A ``null`` for ``receipt`` clears the file: the serializer's field allows it,
# and ``SerializerValidator`` hands the service ``""``, the empty file.
RECEIPT_SPEC = ServiceSpec(
    service=set_receipt,
    validator=SerializerValidator(ReceiptInput),
    instance_selector_spec=INVOICE_LOOKUP,
    permissions=OPEN,
    presenter=PRESENTER,
)

# Asked of DRF's ``IsAuthenticated`` over HTTP and through the kernel's own
# ``dispatch`` alike. Unavailable (409) while sending is paused, a condition
# reading the registered seed. ``send_invoice`` raises a plain ``ServiceError``
# (422) for an empty invoice, which the spec declares, so the schema documents
# the 422 here and on no other operation.
SEND_SPEC = ServiceSpec(
    service=send_invoice,
    instance_selector_spec=INVOICE_LOOKUP,
    permissions=(DRFPermissionCheck([IsAuthenticated]),),
    presenter=PRESENTER,
    affordances=[
        Affordance(
            code="sending_paused",
            reason="Sending is paused.",
            when=lambda *, sending_paused: not sending_paused,
        )
    ],
    metadata={SERVICE_ERROR_METADATA_KEY: True},
)


class IsStaff(BasePermission):
    """Admits staff only; its ``message`` reaches a caller who is signed in."""

    message = "Only staff can list every invoice."

    def has_permission(self, request: Any, view: Any) -> bool:
        return bool(request.user and request.user.is_staff)


# An adapted DRF class refusing a caller nobody authenticated is answered as a
# DRF view answers it: 401 with the first authenticator's challenge. A signed-in
# caller it refuses is a 403 carrying its ``message``.
STAFF_SPEC = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=list_invoices,
    permissions=(DRFPermissionCheck([IsStaff]),),
    presenter=PRESENTER,
)


class IsSuperuser(PermissionCheck):
    """The kernel's own seat: asked of a principal, with no DRF in it."""

    message = "Only a superuser can list the audited invoices."

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return bool(getattr(principal, "is_superuser", False))


# The same refusals from a kernel check: nobody authenticated gets the 401 with
# the challenge, but only where the denial is the dispatched spec's own check; a
# signed-in caller it refuses is still a 403 carrying its ``message``.
AUDIT_SPEC = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=list_invoices,
    permissions=(IsSuperuser(),),
    presenter=PRESENTER,
)

SUMMARY_SPEC = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=list_invoices,
    permissions=OPEN,
    presenter=InvoiceSummaryPresenter(),
)

SENT_SPEC = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=sent_invoices,
    permissions=OPEN,
    presenter=PRESENTER,
)


# ``update_invoice`` raises ``ServiceConflict`` for a sent invoice, a refusal the
# spec cannot show, so it is declared here beside what the schema documents. It
# is on the viewset's methods, not the class: a class decorated before
# ``enable_openapi()`` runs would keep drf-spectacular's own ``AutoSchema``.
@extend_schema_view(
    update=extend_schema(responses={409: ServiceConflictSerializer}),
    partial_update=extend_schema(responses={409: ServiceConflictSerializer}),
)
class InvoiceViewSet(ServiceViewSet):
    """``/invoices/`` and ``/invoices/<pk>/``, plus ``POST /invoices/<pk>/send/``, answers 202.

    No ``"destroy"`` spec: ``DELETE`` answers 405 and the detail route's
    ``Allow`` header leaves it out. ``PATCH`` falls back to the ``"update"``
    spec, validated partially. ``pool_seeds`` registers ``SEEDS`` for every
    action, the decorated one included.
    """

    pool_seeds = SEEDS
    action_specs = {
        "list": LIST_SPEC,
        "retrieve": RETRIEVE_SPEC,
        "create": CREATE_SPEC,
        "update": UPDATE_SPEC,
    }

    # 202: the invoice is marked sent now, its delivery is not promised. The
    # keyword answers for this action only; the rest keep their defaults.
    @service_action(SEND_SPEC, detail=True, methods=["post"], success_status=202)
    def send(self, request: Any, pk: Any = None) -> None:
        """Mark a draft as sent, answered 202."""


class InvoiceImportView(ServiceCreateView):
    """``POST /invoice-imports/``: ``CREATE_SPEC``, whose JSON body its serializer alone answers.

    For a client sending ``5`` for a string, which ``POST /invoices/`` refuses.
    The spec stays typed everywhere else, its schema included.
    """

    spec = CREATE_SPEC
    lenient_json_body = True


class InvoiceReceiptView(ServiceUpdateView):
    """``PATCH /invoices/<pk>/receipt/``: a ``null`` clears the file the invoice holds."""

    spec = RECEIPT_SPEC


class SentInvoiceListView(SelectorListView):
    """``GET /sent-invoices/``: one selector spec on a standalone view."""

    spec = SENT_SPEC


class SummaryInvoiceListView(SelectorListView):
    """``GET /invoice-summaries/``: rows presented by a presenter that is no serializer."""

    spec = SUMMARY_SPEC


class StaffInvoiceListView(SelectorListView):
    """``GET /staff-invoices/``: ``BasicAuthentication`` and an adapted DRF class.

    The project configures no authenticator, so a route without one, such as
    ``/invoices/<pk>/send/``, answers a refused anonymous caller 403; this
    one's ``BasicAuthentication``, like ``AuditInvoiceListView``'s, is the
    ``WWW-Authenticate`` challenge of the 401.
    """

    authentication_classes = [BasicAuthentication]
    spec = STAFF_SPEC


class AuditInvoiceListView(SelectorListView):
    """``GET /audited-invoices/``: ``BasicAuthentication`` and a kernel check.

    The kernel ``PermissionCheck`` ``IsSuperuser`` guards the spec; the view's
    authenticator is what makes a refused anonymous caller a 401 with a
    challenge, as ``StaffInvoiceListView`` does for the adapted DRF class.
    """

    authentication_classes = [BasicAuthentication]
    spec = AUDIT_SPEC


class IsStaffMember(BasePermission):
    """The view's own DRF permission class: no spec check asks it."""

    message = "Only staff can open the review queue."

    def has_permission(self, request: Any, view: Any) -> bool:
        return bool(request.user and request.user.is_staff)


# The spec admits everyone, so the schema would document no 403 and no 401: the
# refusals here are DRF's own, asked of the view before the spec. They are
# declared with the package's exported bodies, the ``PermissionDenied`` and
# ``NotAuthenticated`` components the spec's own refusals use.
@extend_schema(
    responses={
        401: OpenApiResponse(NotAuthenticatedSerializer, description="No credentials were sent."),
        403: OpenApiResponse(PermissionDeniedSerializer, description="The caller is not staff."),
    }
)
class ReviewInvoiceListView(SelectorListView):
    """``GET /review-invoices/``: a view-level permission class, not a spec check."""

    authentication_classes = [BasicAuthentication]
    permission_classes = [IsStaffMember]
    spec = LIST_SPEC


class DraftInvoiceViewSet(ServiceCreateMixin, GenericViewSet):
    """``POST /drafts/``: the create mixin first, ``GenericViewSet`` after it.

    No ``schema`` attribute: with the mixin before ``GenericViewSet``,
    ``enable_openapi()``'s schema is the one this class inherits, so the
    operation documents ``CREATE_SPEC``'s bodies. Listed the other way round,
    ``GenericViewSet``'s own schema would come first and document none of it.
    """

    queryset = Invoice.objects.all()
    action_specs = {"create": CREATE_SPEC}


class IntakeViewSet(ServiceCreateMixin, GenericViewSet):
    """``POST /intake/``: one ``create`` action serving ``INTAKE``, a ``DiscriminatedAction``.

    Composed from the create mixin alone, as ``DraftInvoiceViewSet`` is, so the
    router mounts nothing it does not serve. A body naming ``amount_cents`` is
    validated and created as ``CREATE_SPEC`` does; any other is ``BLANK_SPEC``'s,
    a customer and a zero amount. The schema documents the request as the
    ``IntakeViewSet_create_Request`` component, an ``anyOf`` over both bodies.
    One spec per route stays the default (``InvoiceViewSet``); this is for an
    endpoint that must keep one URL.
    """

    queryset = Invoice.objects.all()
    action_specs = {"create": INTAKE}
