"""Schema-only ``Serializer`` documenting the ``403`` a refused permission check is answered with."""

from __future__ import annotations

from rest_framework import serializers


class _PermissionDeniedList(serializers.ListSerializer):
    """What ``many=True`` of the body builds, a class of its own so the schema can name it.

    ``openapi.utils`` annotates it with the body's component name: the
    pagination naming of a list view then stops at the list rather than asking
    the body's extension, which arms a component nothing takes a ``$ref`` of.
    """


class PermissionDeniedSerializer(serializers.Serializer):
    """The caller may not run this operation. Why is under `detail`."""

    # The docstring above is the component's description in the generated
    # document, so it is written for a client; the reference is
    # docs/openapi.md. ``ServiceAutoSchema`` documents it as the ``403`` of a
    # spec whose checks can refuse, under the component name
    # ``PermissionDenied`` the package keeps; a project declares it over a
    # ``403`` of its own, on any view. The body is DRF's ``PermissionDenied``.

    detail = serializers.CharField()

    class Meta:
        list_serializer_class = _PermissionDeniedList
