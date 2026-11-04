"""Schema-only ``Serializer`` documenting the ``{"detail": ...}`` body of a ``ServiceError``, and its ``schema``."""

from __future__ import annotations

from rest_framework import serializers


class ServiceErrorSerializer(serializers.Serializer):
    """The service could not complete the call. Why is under `detail`, and the values still needed under `schema` where it asks for more input."""

    # The docstring above is the component's description in the generated
    # document, so it is written for a client; the reference is
    # docs/openapi.md. ``ServiceAutoSchema`` documents it as the ``422`` of
    # every spec-driven operation and as the ``detail`` alternative of a
    # Validator's ``400`` (a body that is no object). It is only used for
    # schema generation: ``map_service_error`` answers a ``ServiceError``
    # with ``{"detail": ...}``, and an ``AdditionalInputRequired`` carrying
    # a schema with that schema beside it.

    detail = serializers.CharField()
    schema = serializers.DictField(
        required=False,
        help_text=(
            "The JSON Schema of the values still needed, present only where the "
            "service raised an AdditionalInputRequired carrying one."
        ),
    )
