"""URL routing for the invoices app."""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from invoices.views import InvoiceViewSet, SentInvoiceListView

router = DefaultRouter()
router.register("invoices", InvoiceViewSet, basename="invoice")

urlpatterns = [
    path("sent-invoices/", SentInvoiceListView.as_view(), name="sent-invoices"),
    *router.urls,
]
