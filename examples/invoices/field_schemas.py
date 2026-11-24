"""The project's field schema rules: ``SERVICE_SPECS_FIELD_SCHEMA_REGISTRY`` names this."""

from __future__ import annotations

from django_service_specs import JsonSchemaRegistry

from invoices.serializers import InvoiceCodeField

FIELD_SCHEMAS = JsonSchemaRegistry().extend(fields=[(InvoiceCodeField, {"type": "string"})])
