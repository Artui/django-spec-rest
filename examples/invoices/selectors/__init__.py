"""Selectors, and the FilterSet the list route reads off the query string."""

from __future__ import annotations

import django_filters
from django.db.models import QuerySet

from invoices.models import Invoice


class InvoiceFilter(django_filters.FilterSet):
    """``?status=`` and ``?customer=``, applied by the kernel to the selector's queryset."""

    status = django_filters.ChoiceFilter(choices=Invoice.STATUS_CHOICES)
    customer = django_filters.CharFilter(lookup_expr="icontains")

    class Meta:
        model = Invoice
        fields: list[str] = []


def list_invoices() -> QuerySet[Invoice]:
    return Invoice.objects.all()


def sent_invoices() -> QuerySet[Invoice]:
    return Invoice.objects.filter(status=Invoice.STATUS_SENT)


def get_invoice(*, pk: int) -> Invoice | None:
    # ``None`` is a miss: the kernel answers it as not found, a 404 here.
    return Invoice.objects.filter(pk=pk).first()
