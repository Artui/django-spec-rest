"""Schema-only ``Serializer`` documenting the ``{"detail": ...}`` body of a ``ServiceError``."""

from __future__ import annotations

from rest_framework import serializers


class ServiceErrorSerializer(serializers.Serializer):
    """Single-field ``detail`` serializer that mirrors ``_ServiceAPIException``.

    Used by
    [`ServiceAutoSchema`][django_spec_rest.openapi.service_auto_schema.ServiceAutoSchema]
    to attach a ``422`` response to every spec-driven mutation in the generated OpenAPI
    document, and as the ``detail`` alternative of a Validator's ``400`` (a body that is
    no object). It is *only* used for schema generation; runtime bodies are produced
    by DRF's exception handler."""

    detail = serializers.CharField()
