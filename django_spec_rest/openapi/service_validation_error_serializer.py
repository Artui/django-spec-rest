from __future__ import annotations

from rest_framework import serializers


class ServiceValidationErrorSerializer(serializers.Serializer):
    """Refused as invalid: messages as a list, or by name, each a message, list or object."""

    # The docstring above is the component's description in the generated
    # document, so it is written for a client; the reference is
    # docs/openapi.md. The body is DRF's ``ValidationError(detail)``, which
    # ``map_service_error`` answers a ``ServiceValidationError`` with: a
    # sentence or a list of them as a list, a mapping as an object, and a
    # list of mappings as a list of objects, to any depth. No field can say
    # that, so the class declares none: ``ServiceAutoSchema``'s module
    # registers the drf-spectacular extension that renders it, which
    # ``enable_openapi`` loads.
