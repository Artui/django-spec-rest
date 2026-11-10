from __future__ import annotations

from rest_framework import serializers


class ServiceErrorSerializer(serializers.Serializer):
    """Could not complete the call. Why is under `detail`; values still needed under `schema`."""

    # The docstring above is the component's description, for a client; see docs/openapi.md.

    detail = serializers.CharField()
    schema = serializers.DictField(
        required=False,
        help_text=(
            "The JSON Schema of the values still needed, present only where the "
            "service raised an AdditionalInputRequired carrying one."
        ),
    )
