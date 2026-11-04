"""Schema-only ``Serializer`` documenting the ``403`` a refused permission check is answered with."""

from __future__ import annotations

from rest_framework import serializers


class PermissionDeniedSerializer(serializers.Serializer):
    """The caller may not run this operation. Why is under `detail`."""

    # The docstring above is the component's description in the generated
    # document, so it is written for a client; the reference is
    # docs/openapi.md. ``ServiceAutoSchema`` documents it as the ``403`` of a
    # spec whose checks can refuse, under the component name
    # ``PermissionDenied`` the package keeps; a project declares it over a
    # ``403`` of its own, on any view. The body is DRF's ``PermissionDenied``.

    detail = serializers.CharField()
