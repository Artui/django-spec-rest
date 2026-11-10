from __future__ import annotations

from rest_framework import serializers

from django_spec_rest.openapi.service_conflict_serializer import ServiceConflictSerializer


class ActionUnavailableSerializer(ServiceConflictSerializer):
    """Unavailable in its target's state: ``detail`` says why, ``code`` is stable."""

    # The docstring above is the component's description, for a client; see docs/openapi.md.

    code = serializers.CharField(help_text="The stable code of the action that is unavailable.")
