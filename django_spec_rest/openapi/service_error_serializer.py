"""Schema-only ``Serializer`` documenting the ``{"detail": ...}`` body of a ``ServiceError``, and its ``schema``."""

from __future__ import annotations

from rest_framework import serializers


class ServiceErrorSerializer(serializers.Serializer):
    """``detail`` and the optional ``schema`` serializer that mirrors ``_ServiceAPIException``.

    Used by
    [`ServiceAutoSchema`][django_spec_rest.openapi.service_auto_schema.ServiceAutoSchema]
    to attach a ``422`` response to every spec-driven mutation and selector in the generated OpenAPI
    document, and as the ``detail`` alternative of a Validator's ``400`` (a body that is
    no object). It is *only* used for schema generation; runtime bodies are produced
    by DRF's exception handler."""

    detail = serializers.CharField()
    schema = serializers.DictField(
        required=False,
        help_text=(
            "The JSON Schema of the values still needed, present only where the "
            "service raised an AdditionalInputRequired carrying one."
        ),
    )
