"""Schema-only ``Serializer`` documenting the ``409`` a service's ``ServiceConflict`` is answered with."""

from __future__ import annotations

from rest_framework import serializers


class ServiceConflictSerializer(serializers.Serializer):
    """The call conflicts with the state of what it acts on. Why is under `detail`."""

    # The docstring above is the component's description in the generated
    # document, so it is written for a client; the reference is
    # docs/openapi.md. ``map_service_error`` answers a ``ServiceConflict``
    # with ``{"detail": ...}``, and its ``ActionUnavailable`` with the
    # affordance's ``code`` beside it, so ``code`` is named and not required:
    # a service raising ``ServiceConflict`` may raise either.

    detail = serializers.CharField()
    code = serializers.CharField(
        required=False,
        help_text=(
            "The stable code of the action that is unavailable, present only where "
            "the conflict is an unavailable action."
        ),
    )
