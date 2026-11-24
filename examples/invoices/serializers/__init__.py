"""Serializers: one validates a write's body, one renders an invoice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

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


class BlankInvoiceInput(serializers.Serializer):
    """The body of the intake's second variant: a customer and nothing else."""

    customer = serializers.CharField(max_length=200)


class ReceiptInput(serializers.Serializer):
    """The body of a receipt's route: a file, or a ``null`` that clears the one held."""

    receipt = serializers.FileField(allow_null=True)


@dataclass(frozen=True)
class ReceiptChange:
    receipt: Any = None


class ReceiptChangeInput(DataclassSerializer):
    """The receipt body as a dataclass: a ``null`` clears the file, a key left out keeps it."""

    receipt = serializers.FileField(allow_null=True, required=False)

    class Meta:
        dataclass = ReceiptChange


class InvoiceSerializer(serializers.ModelSerializer):
    """An invoice as every route answers it, with the call's warnings beside it."""

    warnings = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = ("id", "customer", "amount_cents", "notes", "status", "warnings")

    def get_warnings(self, invoice: Invoice) -> list[str]:
        return list(self.context.get("warnings", []))


class InvoiceCodeField(serializers.IntegerField):
    """An invoice's code, ``INV-<id>``: a string on the wire, though an ``IntegerField``."""

    def to_representation(self, value: int) -> str:
        return f"INV-{value}"


class CodedInvoiceSerializer(serializers.Serializer):
    """A code and the rank the list view's hook hands in for the page, one dict for the page."""

    code = InvoiceCodeField(source="pk", read_only=True)
    rank = serializers.SerializerMethodField()

    def get_rank(self, invoice: Invoice) -> int | None:
        return self.context.get("ranks", {}).get(invoice.pk)


class PlainCodedInvoiceSerializer(CodedInvoiceSerializer):
    """The same fields, presented by a seat that opts out of the project's field rules."""
