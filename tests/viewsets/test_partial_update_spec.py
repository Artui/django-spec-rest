"""PATCH and PUT on a viewset serving kernel specs.

A PATCH dispatches the spec's partial variant, a PUT the spec as declared, and
a spec declaring ``partial=True`` takes a PUT partially too, as on
``ServiceUpdateView``. A ``"partial_update"`` entry wins for PATCH, and PATCH
falls back to ``"update"``.
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
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceViewSet, service_action
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()


class _NameIn(serializers.Serializer):
    name = serializers.CharField()
    note = serializers.CharField()


def _rename(*, instance: Author, data: dict[str, Any]) -> Author:
    instance.name = data.get("name", instance.name)
    instance.save(update_fields=["name"])
    return instance


def _update(**fields: Any) -> ServiceSpec:
    defaults: dict[str, Any] = {
        "service": _rename,
        "permissions": (Unrestricted(),),
        "validator": SerializerValidator(_NameIn),
        "presenter": SerializerPresenter(AuthorSerializer),
        "instance_selector_spec": SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
        ),
    }
    return ServiceSpec(**{**defaults, **fields})


def _viewset(**action_specs: ServiceSpec) -> Any:
    return type("_ViewSet", (ServiceViewSet,), {"action_specs": action_specs})


def _send(viewset: Any, method: str, body: Any, pk: int) -> Response:
    action_name = "partial_update" if method == "patch" else "update"
    request = getattr(factory, method)("/", body, format="json")
    return viewset.as_view({method: action_name})(request, pk=pk)


@pytest.fixture
def author() -> Author:
    return Author.objects.create(name="a")


class TestPartial:
    def test_a_patch_validates_only_what_it_sends(self, author: Author) -> None:
        response = _send(_viewset(update=_update()), "patch", {"name": "b"}, author.pk)
        assert response.status_code == 200
        assert response.data["name"] == "b"

    def test_a_put_validates_every_field(self, author: Author) -> None:
        response = _send(_viewset(update=_update()), "put", {"name": "b"}, author.pk)
        assert response.status_code == 400
        assert "note" in response.data

    def test_a_partial_spec_takes_a_put_partially(self, author: Author) -> None:
        response = _send(_viewset(update=_update(partial=True)), "put", {"name": "b"}, author.pk)
        assert response.status_code == 200

    def test_a_service_action_s_partial_spec_validates_partially(self, author: Author) -> None:
        class _ViewSet(ServiceViewSet):
            @service_action(_update(partial=True), detail=True, methods=["post"])
            def rename(self, request: Any, pk: Any = None) -> None:
                """Stubbed."""

        request = factory.post("/", {"name": "b"}, format="json")
        assert _ViewSet.as_view({"post": "rename"})(request, pk=author.pk).status_code == 200


class TestTheActionKeys:
    def test_a_partial_update_entry_wins_for_a_patch(self, author: Author) -> None:
        def mark(*, instance: Author, data: dict[str, Any]) -> Author:
            instance.name = "patched"
            instance.save(update_fields=["name"])
            return instance

        viewset = _viewset(update=_update(), partial_update=_update(service=mark))
        assert _send(viewset, "patch", {"name": "b"}, author.pk).data["name"] == "patched"
        assert _send(viewset, "put", {"name": "c", "note": "n"}, author.pk).data["name"] == "c"

    def test_a_patch_with_neither_entry_is_405(self, author: Author) -> None:
        assert _send(_viewset(), "patch", {"name": "b"}, author.pk).status_code == 405
