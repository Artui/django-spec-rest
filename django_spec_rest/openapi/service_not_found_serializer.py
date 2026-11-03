"""Schema-only ``Serializer`` documenting the ``404`` a service's ``ServiceNotFound`` is answered with."""

from __future__ import annotations

from rest_framework import serializers


class ServiceNotFoundSerializer(serializers.Serializer):
    """The service found nothing to act on. Why is under `detail`."""

    # The docstring above is the component's description in the generated
    # document, so it is written for a client; the reference is
    # docs/openapi.md. The body is DRF's ``NotFound(str(exc))``, which
    # ``map_service_error`` answers a ``ServiceNotFound`` with.

    detail = serializers.CharField()
