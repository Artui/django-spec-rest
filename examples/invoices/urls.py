"""URL routing for the invoices app."""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from invoices.views import (
    AuditInvoiceListView,
    InvoiceViewSet,
    SentInvoiceListView,
    StaffInvoiceListView,
)

router = DefaultRouter()
router.register("invoices", InvoiceViewSet, basename="invoice")

urlpatterns = [
    path("sent-invoices/", SentInvoiceListView.as_view(), name="sent-invoices"),
    path("staff-invoices/", StaffInvoiceListView.as_view(), name="staff-invoices"),
    path("audited-invoices/", AuditInvoiceListView.as_view(), name="audited-invoices"),
    *router.urls,
]
