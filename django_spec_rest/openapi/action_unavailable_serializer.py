"""Schema-only ``Serializer`` documenting the ``409`` a service's ``ActionUnavailable`` is answered with."""

from __future__ import annotations

from rest_framework import serializers

from django_spec_rest.openapi.service_conflict_serializer import ServiceConflictSerializer


class ActionUnavailableSerializer(ServiceConflictSerializer):
    """The action is unavailable in the state of what it acts on. Why is under `detail`, and the action's stable code under `code`."""

    # The docstring above is the component's description in the generated
    # document, so it is written for a client; the reference is
    # docs/openapi.md. ``map_service_error`` always sends the ``code``,
    # since an ``ActionUnavailable`` cannot be built without one.

    code = serializers.CharField(help_text="The stable code of the action that is unavailable.")
