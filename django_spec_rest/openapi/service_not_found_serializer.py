from __future__ import annotations

from rest_framework import serializers


class ServiceNotFoundSerializer(serializers.Serializer):
    """The service found nothing to act on. Why is under `detail`."""

    # The docstring above is the component's description, for a client; see docs/openapi.md.

    detail = serializers.CharField()
