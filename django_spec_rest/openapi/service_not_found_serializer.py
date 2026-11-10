from __future__ import annotations

from rest_framework import serializers


class ServiceNotFoundSerializer(serializers.Serializer):
    """The service found nothing to act on. Why is under `detail`."""

    # The docstring above is the component's description in the generated document, so it is written for a client; the reference is docs/openapi.md.

    detail = serializers.CharField()
