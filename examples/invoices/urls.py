"""URL routing for the invoices app."""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from invoices.views import (
    AuditInvoiceListView,
    DraftInvoiceViewSet,
    IntakeViewSet,
    InvoiceImportView,
    InvoiceReceiptView,
    InvoiceViewSet,
    ReviewInvoiceListView,
    SentInvoiceListView,
    StaffInvoiceListView,
    SummaryInvoiceListView,
)

router = DefaultRouter()
router.register("invoices", InvoiceViewSet, basename="invoice")
router.register("intake", IntakeViewSet, basename="intake")
router.register("drafts", DraftInvoiceViewSet, basename="draft")

urlpatterns = [
    path("invoice-imports/", InvoiceImportView.as_view(), name="invoice-imports"),
    path("invoices/<int:pk>/receipt/", InvoiceReceiptView.as_view(), name="invoice-receipt"),
    path("sent-invoices/", SentInvoiceListView.as_view(), name="sent-invoices"),
    path("invoice-summaries/", SummaryInvoiceListView.as_view(), name="invoice-summaries"),
    path("staff-invoices/", StaffInvoiceListView.as_view(), name="staff-invoices"),
    path("audited-invoices/", AuditInvoiceListView.as_view(), name="audited-invoices"),
    path("review-invoices/", ReviewInvoiceListView.as_view(), name="review-invoices"),
    *router.urls,
]
