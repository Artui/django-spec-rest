"""URL routing for the invoices app."""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from invoices.views import (
    AuditInvoiceListView,
    DraftInvoiceViewSet,
    InvoiceViewSet,
    ReviewInvoiceListView,
    SentInvoiceListView,
    StaffInvoiceListView,
)

router = DefaultRouter()
router.register("invoices", InvoiceViewSet, basename="invoice")
router.register("drafts", DraftInvoiceViewSet, basename="draft")

urlpatterns = [
    path("sent-invoices/", SentInvoiceListView.as_view(), name="sent-invoices"),
    path("staff-invoices/", StaffInvoiceListView.as_view(), name="staff-invoices"),
    path("audited-invoices/", AuditInvoiceListView.as_view(), name="audited-invoices"),
    path("review-invoices/", ReviewInvoiceListView.as_view(), name="review-invoices"),
    *router.urls,
]
