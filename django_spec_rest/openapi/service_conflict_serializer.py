from __future__ import annotations

from rest_framework import serializers


class ServiceConflictSerializer(serializers.Serializer):
    """The call conflicts with the state of what it acts on. Why is under `detail`."""

    # The docstring above is the component's description in the generated document, so it is written for a client; the reference is docs/openapi.md.

    detail = serializers.CharField()
    code = serializers.CharField(
        required=False,
        help_text=(
            "The stable code of the action that is unavailable, present only where "
            "the conflict is an unavailable action."
        ),
    )
