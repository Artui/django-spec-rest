"""Serializers: one validates a write's body, one renders an invoice."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from invoices.models import Invoice


class InvoiceInput(serializers.Serializer):
    """The body of a create, and of an update, which sends a subset of it.

    ``validate`` writes a note into its ``context`` for the serializer that
    renders the answer: the call hands both serializers the request's one
    context dict, so what one writes the other reads.
    """

    customer = serializers.CharField(max_length=200)
    amount_cents = serializers.IntegerField(min_value=0)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("amount_cents") == 0:
            self.context.setdefault("warnings", []).append("The amount is zero.")
        return attrs


class InvoiceSerializer(serializers.ModelSerializer):
    """An invoice as every route answers it, with the call's warnings beside it."""

    warnings = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = ("id", "customer", "amount_cents", "notes", "status", "warnings")

    def get_warnings(self, invoice: Invoice) -> list[str]:
        return list(self.context.get("warnings", []))
