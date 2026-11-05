"""Schema-only ``Serializer`` documenting the ``401`` a caller nobody authenticated is answered with."""

from __future__ import annotations

from rest_framework import serializers


class _NotAuthenticatedList(serializers.ListSerializer):
    """What ``many=True`` of the body builds, a class of its own so the schema can name it.

    ``openapi.utils`` annotates it with the body's component name: the
    pagination naming of a list view then stops at the list rather than asking
    the body's extension, which arms a component nothing takes a ``$ref`` of.
    """


class NotAuthenticatedSerializer(serializers.Serializer):
    """No caller was authenticated. Why is under `detail`."""

    # The docstring above is the component's description in the generated
    # document, so it is written for a client; the reference is
    # docs/openapi.md. ``ServiceAutoSchema`` documents it as the ``401`` of a
    # spec whose checks can refuse, behind an authenticator with a challenge,
    # under the component name ``NotAuthenticated`` the package keeps; a
    # project declares it over a ``401`` of its own, on any view. The body is
    # DRF's ``NotAuthenticated``.

    detail = serializers.CharField()

    class Meta:
        list_serializer_class = _NotAuthenticatedList
