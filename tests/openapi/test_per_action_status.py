"""The status a viewset's operation documents is the one its action answers with.

The per-action value outranks the viewset's: a decorated action's
``success_status`` and an ``action_specs`` entry's ``get_<action>_success_status``
are documented where they are an ``int``, and a per-action callable documents
the action's default rather than the viewset-wide ``int`` it replaces. The
viewset is built inside the fixture, so a tree whose ``@service_action`` takes
no ``success_status`` fails these tests, not the module's import.
"""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from drf_spectacular.generators import SchemaGenerator
from rest_framework import serializers
from rest_framework.routers import SimpleRouter

from django_spec_rest import ServiceViewSet, service_action
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

_OPEN = (Unrestricted(),)


class _NameIn(serializers.Serializer):
    name = serializers.CharField(max_length=20)


def _write(**fields: Any) -> ServiceSpec:
    defaults: dict[str, Any] = {
        "service": lambda *, data: None,
        "permissions": _OPEN,
        "validator": SerializerValidator(_NameIn),
        "presenter": SerializerPresenter(AuthorSerializer),
    }
    return ServiceSpec(**{**defaults, **fields})


def _target() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: None,
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
    )


def _viewset() -> type:
    @service_action(_write(), methods=["post"], success_status=201)
    def enrol(self: Any, request: Any) -> None:
        """Stubbed: the decorator serves the spec."""

    @service_action(_write(), methods=["post"])
    def note(self: Any, request: Any) -> None:
        """Stubbed: the decorator serves the spec."""

    def get_create_success_status(self: Any, *, result: Any) -> int:
        return 201

    return type(
        "_ViewSet",
        (ServiceViewSet,),
        {
            "queryset": Author.objects.all(),
            "action_specs": {
                "create": _write(),
                "update": _write(instance_selector_spec=_target()),
            },
            "success_status": 202,
            "enrol": enrol,
            "note": note,
            "get_create_success_status": get_create_success_status,
            "get_update_success_status": 203,
        },
    )


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    enable_openapi()
    router = SimpleRouter()
    router.register("authors", _viewset(), basename="authors")
    return SchemaGenerator(patterns=router.urls).get_schema(request=None, public=True)


def _statuses(schema: dict[str, Any], route: str, method: str) -> set[str]:
    return set(schema["paths"][route][method]["responses"]) - {"400"}


def test_a_decorated_action_s_int_is_documented(schema: dict[str, Any]) -> None:
    assert _statuses(schema, "/authors/enrol/", "post") == {"201"}


def test_a_decorated_action_naming_none_documents_the_viewset_s(schema: dict[str, Any]) -> None:
    assert _statuses(schema, "/authors/note/", "post") == {"202"}


def test_an_entry_s_int_hook_is_documented(schema: dict[str, Any]) -> None:
    assert _statuses(schema, "/authors/{id}/", "put") == {"203"}


def test_an_entry_s_callable_hook_documents_the_action_s_default(schema: dict[str, Any]) -> None:
    # Not the viewset's 202, which the hook replaces for this action.
    assert _statuses(schema, "/authors/", "post") == {"201"}
