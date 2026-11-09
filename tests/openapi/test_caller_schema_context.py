"""OPTIONS and the OpenAPI body read a spec under the ``rest`` stamp, as dispatch does.

A Validator may declare fields by call (``parameters(self, *, call_context=None)``).
Dispatch asks it under the view's stamped dict, so each describing seat asks the
same: OPTIONS with the call's own dict, OpenAPI with a dict naming the transport
and no request, since a document describes the transport and never one caller.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from django.urls import path
from django_service_specs import (
    Parameter,
    Parameters,
    ServiceSpec,
    Unrestricted,
    ValidationContext,
    Validator,
    call_transport,
)
from drf_spectacular.generators import SchemaGenerator
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from django_spec_rest import REST_TRANSPORT, ServiceCreateView, ServiceViewSet, service_action
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.types.discriminated_action import DiscriminatedAction
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db

_OPEN = (Unrestricted(),)
_NAME = Parameter("name", "string", required=True)
_HANDED: list[dict[str, Any]] = []


class _Echo(Validator):
    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return dict(arguments)


class _ByTransport(_Echo):
    """``ticket`` is declared to ``rest`` and required; ``flag`` to ``cli`` alone."""

    def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
        transport = call_transport(call_context) if call_context is not None else None
        if transport == REST_TRANSPORT:
            return Parameters.of(_NAME, Parameter("ticket", "string", required=True))
        if transport == "cli":
            return Parameters.of(_NAME, Parameter("flag", "string", required=True))
        return Parameters.of(_NAME)


class _ByAction(_Echo):
    """``via_<action>`` is required where the call names an action, as a Validator keyed on it may."""

    def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
        action = call_context["action"] if call_context is not None else None
        if action is None:
            return Parameters.of(_NAME)
        return Parameters.of(_NAME, Parameter(f"via_{action}", "string", required=True))


class _Unguarded(_Echo):
    """Guards the context and then reads an attribute of its ``request``, unguarded."""

    def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
        if call_context is None:
            return Parameters.of(_NAME)
        tenant = call_context["request"].tenant
        return Parameters.of(_NAME, Parameter(tenant, "string"))


class _Refusing(_Echo):
    """Raises an exception OPTIONS does not read as 'cannot be described'."""

    def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
        raise ValueError("not describable")


class _Guarded(_Echo):
    """Guards ``request`` too, as the docs ask: a per-caller field only where one is in hand."""

    def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
        if call_context is None or call_context["request"] is None:
            return Parameters.of(_NAME)
        return Parameters.of(_NAME, Parameter("per_caller", "string"))


class _Plain(serializers.Serializer):
    name = serializers.CharField()
    note = serializers.CharField(required=False)


def _service(**kwargs: Any) -> None:
    _HANDED.append(kwargs)


def _spec(validator: Validator, **fields: Any) -> ServiceSpec:
    return ServiceSpec(
        service=_service, permissions=_OPEN, validator=validator, allow_none=True, **fields
    )


def _view(spec: ServiceSpec) -> type[ServiceCreateView]:
    return type("View", (ServiceCreateView,), {"spec": spec})


def _route(view: type[APIView], route: str, **initkwargs: Any) -> Any:
    return path(route, view.as_view(**initkwargs))


def _options(view: Any, method: str = "POST") -> dict[str, Any]:
    return view(APIRequestFactory().options("/")).data["actions"][method]


def _document(*patterns: Any) -> dict[str, Any]:
    return SchemaGenerator(patterns=list(patterns)).get_schema(request=None, public=True)


def _schema_of(document: dict[str, Any], route: str) -> dict[str, Any]:
    body = document["paths"][route]["post"]["requestBody"]["content"]["application/json"]
    return body["schema"]


BY_TRANSPORT = _view(_spec(_ByTransport()))


class ByAction(ServiceViewSet):
    """``create`` and a ``PUT`` action, each a spec naming the action its call is dispatched under."""

    queryset = Author.objects.all()
    action_specs = {"create": _spec(_ByAction())}

    @service_action(_spec(_ByAction()), detail=False, methods=["put"])
    def replace(self, request: Any) -> Any: ...


_BY_ACTION_ROUTES = {"post": "create", "put": "replace"}


class Discriminated(ServiceViewSet):
    queryset = Author.objects.all()
    action_specs = {
        "create": DiscriminatedAction(
            lambda: "stamped", {"stamped": _spec(_ByTransport()), "plain": _spec(_ByTransport())}
        )
    }


@pytest.fixture(scope="module", autouse=True)
def _enable_openapi() -> None:
    enable_openapi()


class TestAFieldDeclaredToThisTransport:
    def test_it_is_in_options_and_required(self) -> None:
        described = _options(BY_TRANSPORT.as_view())
        assert set(described["properties"]) == {"name", "ticket"}
        assert sorted(described["required"]) == ["name", "ticket"]

    def test_it_is_in_the_document_and_required(self) -> None:
        body = _schema_of(_document(_route(BY_TRANSPORT, "t/")), "/t/")
        assert set(body["properties"]) == {"name", "ticket"}
        assert sorted(body["required"]) == ["name", "ticket"]

    def test_a_post_sending_it_succeeds(self) -> None:
        _HANDED.clear()
        response = BY_TRANSPORT.as_view()(
            APIRequestFactory().post("/", {"name": "n", "ticket": "t"}, format="json")
        )
        assert response.status_code == 204
        (handed,) = _HANDED
        assert (handed["name"], handed["ticket"]) == ("n", "t")

    def test_a_post_leaving_it_out_is_the_400_the_document_says(self) -> None:
        response = BY_TRANSPORT.as_view()(
            APIRequestFactory().post("/", {"name": "n"}, format="json")
        )
        assert response.status_code == 400
        assert set(response.data) == {"ticket"}


class TestAFieldDeclaredToAnotherTransport:
    def test_it_is_in_neither(self) -> None:
        described = _options(BY_TRANSPORT.as_view())
        body = _schema_of(_document(_route(BY_TRANSPORT, "t/")), "/t/")
        assert "flag" not in described["properties"]
        assert "flag" not in body["properties"]

    def test_options_and_the_document_agree_on_properties(self) -> None:
        described = _options(BY_TRANSPORT.as_view())
        body = _schema_of(_document(_route(BY_TRANSPORT, "t/")), "/t/")
        assert set(described["properties"]) == set(body["properties"])

    def test_a_discriminated_variant_agrees_too(self) -> None:
        view = Discriminated.as_view({"post": "create"})
        document = _document(path("d/", view))
        ref = _schema_of(document, "/d/")["$ref"].rsplit("/", 1)[1]
        documented = document["components"]["schemas"][ref]["anyOf"]
        described = _options(view)
        # Variants of one body are one member on both seats.
        members = described.get("anyOf", [described])
        assert [set(m["properties"]) for m in documented] == [{"name", "ticket"}]
        assert [set(m["properties"]) for m in members] == [{"name", "ticket"}]


class TestAFieldKeyedOnTheAction:
    """The wire names the action its call is dispatched under, so each describing seat does too."""

    def test_a_standalone_view_dispatches_no_action_so_neither_seat_names_one(self) -> None:
        _HANDED.clear()
        view = _view(_spec(_ByAction()))
        assert set(_options(view.as_view())["properties"]) == {"name"}
        assert set(_schema_of(_document(_route(view, "s/")), "/s/")["properties"]) == {"name"}
        response = view.as_view()(APIRequestFactory().post("/", {"name": "n"}, format="json"))
        assert response.status_code == 204

    def test_the_document_names_the_action_the_post_dispatches(self) -> None:
        view = ByAction.as_view(_BY_ACTION_ROUTES)
        document = _document(path("a/", view))
        body = document["paths"]["/a/"]["post"]["requestBody"]["content"]["application/json"]
        assert set(body["schema"]["properties"]) == {"name", "via_create"}
        assert sorted(body["schema"]["required"]) == ["name", "via_create"]
        put = document["paths"]["/a/"]["put"]["requestBody"]["content"]["application/json"]
        assert sorted(put["schema"]["required"]) == ["name", "via_replace"]

    def test_options_names_the_action_each_method_dispatches(self) -> None:
        actions = ByAction.as_view(_BY_ACTION_ROUTES)(APIRequestFactory().options("/")).data[
            "actions"
        ]
        assert sorted(actions["POST"]["required"]) == ["name", "via_create"]
        assert sorted(actions["PUT"]["required"]) == ["name", "via_replace"]

    def test_the_wire_requires_the_field_the_seats_name(self) -> None:
        view = ByAction.as_view(_BY_ACTION_ROUTES)
        response = view(APIRequestFactory().post("/", {"name": "n"}, format="json"))
        assert response.status_code == 400
        assert set(response.data) == {"via_create"}
        response = view(APIRequestFactory().put("/", {"name": "n"}, format="json"))
        assert set(response.data) == {"via_replace"}

    def test_options_leaves_the_view_s_own_dict_alone(self) -> None:
        seen: list[Any] = []

        class Looking(_ByAction):
            def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
                seen.append(call_context)
                return super().parameters(call_context=call_context)

        class Viewset(ByAction):
            action_specs = {"create": _spec(Looking())}

        view = Viewset.as_view({"post": "create"})
        response = view(APIRequestFactory().options("/"))
        assert response.status_code == 200
        assert {context["action"] for context in seen if context is not None} == {"create"}
        # The dict the view keeps, which dispatch and other stages share, still names OPTIONS.
        assert response.renderer_context["view"]._call_context["action"] == "metadata"


class TestASerializerValidatorDoesNotMove:
    """``describe_serializer`` takes its unbound arm on both seats, whatever dict it is handed."""

    def test_options_is_unchanged(self) -> None:
        described = _options(_view(_spec(SerializerValidator(_Plain))).as_view())
        assert set(described["properties"]) == {"name", "note"}
        assert described["required"] == ["name"]

    def test_the_document_is_unchanged(self) -> None:
        document = _document(_route(_view(_spec(SerializerValidator(_Plain))), "p/"))
        assert _schema_of(document, "/p/") == {"$ref": "#/components/schemas/_Plain"}
        component = document["components"]["schemas"]["_Plain"]
        assert set(component["properties"]) == {"name", "note"}
        assert component["required"] == ["name"]


class TestADescriptionThatRaises:
    """Reading an attribute of ``request`` raises where nothing gave one: each seat keeps its handling."""

    def test_it_raises_out_of_generation(self) -> None:
        # The document has no request, so ``call_context["request"]`` is ``None``.
        with pytest.raises(AttributeError, match="tenant"):
            _document(_route(_view(_spec(_Unguarded())), "u/"))

    def test_it_is_left_out_of_options(self) -> None:
        # A real request here, with no such attribute: the method stays routed
        # and is not described.
        response = _view(_spec(_Unguarded())).as_view()(APIRequestFactory().options("/"))
        assert response.status_code == 200
        assert "POST" not in response.data.get("actions", {})

    def test_any_other_exception_is_not_left_out_of_options(self) -> None:
        # Only AttributeError, KeyError and TypeError leave a method out; a
        # ValueError is a 500, as the docs say.
        with pytest.raises(ValueError, match="not describable"):
            _view(_spec(_Refusing())).as_view()(APIRequestFactory().options("/"))

    def test_a_validator_guarding_request_is_read_on_both_seats(self) -> None:
        view = _view(_spec(_Guarded()))
        # One caller in hand, so its field is offered there and in no document.
        assert set(_options(view.as_view())["properties"]) == {"name", "per_caller"}
        assert set(_schema_of(_document(_route(view, "g/")), "/g/")["properties"]) == {"name"}


class TestTheDictEachSeatHands:
    def test_options_hands_the_view_s_own_dict(self) -> None:
        seen: list[Any] = []

        class Looking(_Echo):
            def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
                seen.append(call_context)
                return Parameters.of(_NAME)

        _options(_view(_spec(Looking())).as_view())
        asks = [context for context in seen if context is not None]
        assert asks
        assert all(isinstance(context["request"], Request) for context in asks)
        assert all(context["transport"] == REST_TRANSPORT for context in asks)

    def test_the_document_hands_the_stamp_the_view_and_no_request(self) -> None:
        seen: list[Any] = []

        class Looking(_Echo):
            def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
                seen.append(call_context)
                return Parameters.of(_NAME)

        view = _view(_spec(Looking()))
        _document(_route(view, "l/"))
        asks = [context for context in seen if context is not None]
        assert asks
        assert all(context["transport"] == REST_TRANSPORT for context in asks)
        assert all(context["request"] is None for context in asks)
        assert all(isinstance(context["view"], view) for context in asks)
