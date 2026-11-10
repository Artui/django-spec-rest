from __future__ import annotations

from rest_framework import serializers


class ServiceErrorSerializer(serializers.Serializer):
    """The service could not complete the call. Why is under `detail`, and the values still needed under `schema` where it asks for more input."""

    # The docstring above is the component's description in the generated document, so it is written for a client; the reference is docs/openapi.md.

    detail = serializers.CharField()
    schema = serializers.DictField(
        required=False,
        help_text=(
            "The JSON Schema of the values still needed, present only where the "
            "service raised an AdditionalInputRequired carrying one."
        ),
    )
