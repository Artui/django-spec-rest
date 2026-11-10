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

    # The docstring above is the component's description, for a client; see docs/openapi.md.

    detail = serializers.CharField()

    class Meta:
        list_serializer_class = _PermissionDeniedList
