from __future__ import annotations

from typing import Any

import pytest
from django.test import override_settings
from django.urls import path
from django_service_specs import (
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
    output_schema,
    parameters_schema,
)
from django_service_specs.types.json_schema_registry import JsonSchemaRegistry
from django_service_specs.types.unknown_arguments import UnknownArguments
from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.extensions import OpenApiSerializerFieldExtension
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.settings import patched_settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.validation import validate_schema
from rest_framework import serializers

from django_spec_rest import SelectorListView, ServiceCreateView, ServiceViewSet
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.types.discriminated_action import DiscriminatedAction
from tests.testapp.models import Author
from tests.views.linked_views import LISTING

enable_openapi()

pytestmark = pytest.mark.django_db

_OPEN = (Unrestricted(),)
_SETTING = "SERVICE_SPECS_FIELD_SCHEMA_REGISTRY"
_HERE = "tests.openapi.test_field_schema_rules"


class LooseIntField(serializers.IntegerField):
    def to_internal_value(self, data: Any) -> Any:
        return data

    def to_representation(self, value: Any) -> Any:
        return value


@extend_schema_field(OpenApiTypes.BOOL)
class AnnotatedIntField(serializers.IntegerField): ...


class RulesInner(serializers.Serializer):
    code = LooseIntField()


class RulesIn(serializers.Serializer):
    code = LooseIntField()
    inner = RulesInner(required=False)
    codes = serializers.ListField(child=LooseIntField(), required=False)
    rows = RulesInner(many=True, required=False)
    plain = serializers.IntegerField(required=False)


class RulesOut(serializers.Serializer):
    code = LooseIntField()
    inner = RulesInner()
    codes = serializers.ListField(child=LooseIntField())
    plain = serializers.IntegerField()


PROJECT = JsonSchemaRegistry(fields=((LooseIntField, {"type": "string"}),))
SEAT = JsonSchemaRegistry(fields=((LooseIntField, {"type": "string"}),))
_PATHS = ("code", "inner.code", "codes[]")


def _project(name: str = "PROJECT") -> Any:
    return override_settings(**{_SETTING: f"{_HERE}.{name}"})


def _service(**_: Any) -> dict[str, Any]:
    return {}


def _rows(**_: Any) -> list[Any]:
    return []


def _spec(validator: Any = None, presenter: Any = None) -> ServiceSpec:
    return ServiceSpec(
        service=_service, permissions=_OPEN, validator=validator, presenter=presenter
    )


def _document(*views: tuple[str, Any]) -> dict[str, Any]:
    patterns = [path(route, view) for route, view in views]
    return SchemaGenerator(patterns=patterns).get_schema(request=None, public=True)


def _created(spec: ServiceSpec) -> Any:
    return type("RulesView", (ServiceCreateView,), {"spec": spec}).as_view()


def _resolved(document: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref") or next(
        (member["$ref"] for member in schema.get("allOf", ()) if "$ref" in member), None
    )
    if ref is None:
        return schema
    return document["components"]["schemas"][ref.rsplit("/", 1)[1]]


def _at(document: dict[str, Any], schema: dict[str, Any], dotted: str) -> dict[str, Any]:
    """The schema at ``dotted`` (``a.b``, ``a[]``) under ``schema``, refs followed."""
    for step in dotted.split("."):
        schema = _resolved(document, schema)
        listed = step.endswith("[]")
        schema = _resolved(document, schema["properties"][step.removesuffix("[]")])
        if listed:
            schema = schema["items"]
    return _resolved(document, schema)


def _types(document: dict[str, Any], component: str) -> dict[str, Any]:
    root = document["components"]["schemas"][component]
    return {dotted: _at(document, root, dotted).get("type") for dotted in _PATHS}


def _compiled(schema: dict[str, Any]) -> dict[str, Any]:
    """The same paths' types in a compiled kernel schema."""
    found: dict[str, Any] = {}
    for dotted in _PATHS:
        at = schema
        for step in dotted.split("."):
            at = at["properties"][step.removesuffix("[]")]
            if step.endswith("[]"):
                at = at["items"]
        found[dotted] = at["type"]
    return found


def _properties(document: dict[str, Any], component: str) -> dict[str, Any]:
    return document["components"]["schemas"][component]["properties"]


@pytest.fixture
def warned(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The warnings drf-spectacular is asked to emit, which it prints once and then caches."""
    emitted: list[str] = []

    def emit(message: str, severity: str) -> None:
        if severity == "warning":
            emitted.append(message)

    monkeypatch.setattr(GENERATOR_STATS, "emit", emit)
    return emitted


# -- The project's rules -------------------------------------------------------------


def test_a_project_rule_types_the_request_and_response_components_as_the_compiled_spec() -> None:
    validator, presenter = SerializerValidator(RulesIn), SerializerPresenter(RulesOut)
    view = _created(_spec(validator, presenter))
    with _project():
        document = _document(("r/", view))
        parameters = parameters_schema(
            validator.parameters(), unknown_arguments=UnknownArguments.IGNORE
        )
        output = output_schema(presenter.output())
    assert _types(document, "RulesIn") == _compiled(parameters) == dict.fromkeys(_PATHS, "string")
    assert _types(document, "RulesOut") == _compiled(output) == dict.fromkeys(_PATHS, "string")


def test_an_unregistered_field_keeps_spectacular_s_mapping() -> None:
    view = _created(_spec(SerializerValidator(RulesIn), SerializerPresenter(RulesOut)))
    with _project():
        document = _document(("r/", view))
    assert _properties(document, "RulesIn")["plain"] == {"type": "integer"}
    assert _properties(document, "RulesOut")["plain"] == {"type": "integer"}


def test_without_a_rule_the_document_is_spectacular_s() -> None:
    view = _created(_spec(SerializerValidator(RulesIn), SerializerPresenter(RulesOut)))
    document = _document(("r/", view))
    assert _types(document, "RulesIn") == dict.fromkeys(_PATHS, "integer")
    assert _types(document, "RulesOut") == dict.fromkeys(_PATHS, "integer")


def test_a_seat_opted_out_of_the_project_s_rules_documents_spectacular_s_mapping() -> None:
    view = _created(
        _spec(
            SerializerValidator(RulesIn, project_registry=False),
            SerializerPresenter(RulesOut, project_registry=False),
        )
    )
    with _project():
        document = _document(("r/", view))
    assert _types(document, "RulesIn") == dict.fromkeys(_PATHS, "integer")
    assert _types(document, "RulesOut") == dict.fromkeys(_PATHS, "integer")


def test_a_serializer_with_no_seat_reads_the_project_s_rules() -> None:
    class Plain(ServiceViewSet):
        queryset = Author.objects.all()
        serializer_class = RulesOut

        def list(self, request: Any) -> Any: ...

    with _project():
        document = _document(("p/", Plain.as_view({"get": "list"})))
    assert _types(document, "RulesOut") == dict.fromkeys(_PATHS, "string")


# -- A seat's own rules --------------------------------------------------------------


def test_a_seat_rule_types_the_request_and_response_components_as_the_compiled_spec() -> None:
    validator = SerializerValidator(RulesIn, json_schema_registry=SEAT)
    presenter = SerializerPresenter(RulesOut, json_schema_registry=SEAT)
    document = _document(("r/", _created(_spec(validator, presenter))))
    parameters = parameters_schema(
        validator.parameters(), unknown_arguments=UnknownArguments.IGNORE
    )
    assert _types(document, "RulesIn") == _compiled(parameters) == dict.fromkeys(_PATHS, "string")
    output = output_schema(presenter.output())
    assert _types(document, "RulesOut") == _compiled(output) == dict.fromkeys(_PATHS, "string")


def test_a_seat_rule_types_a_listed_selector_s_rows() -> None:
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=_rows,
        permissions=_OPEN,
        presenter=SerializerPresenter(RulesOut, json_schema_registry=SEAT),
    )
    view = type("RulesList", (SelectorListView,), {"spec": spec}).as_view()
    document = _document(("l/", view))
    assert _types(document, "RulesOut") == dict.fromkeys(_PATHS, "string")


def test_a_seat_rule_types_a_many_body() -> None:
    validator = SerializerValidator(RulesIn, json_schema_registry=SEAT)
    spec = ServiceSpec(service=_service, permissions=_OPEN, validator=validator, many=True)
    document = _document(("m/", _created(spec)))
    assert _types(document, "RulesIn") == dict.fromkeys(_PATHS, "string")


def test_a_discriminated_action_types_each_variant_by_its_own_seat() -> None:
    class Chooser(ServiceViewSet):
        queryset = Author.objects.all()
        action_specs = {
            "create": DiscriminatedAction(
                lambda request: "a",
                {
                    "a": _spec(
                        SerializerValidator(RulesIn, json_schema_registry=SEAT),
                        SerializerPresenter(RulesOut, json_schema_registry=SEAT),
                    )
                },
            )
        }

    document = _document(("c/", Chooser.as_view({"post": "create"})))
    assert _types(document, "RulesIn") == dict.fromkeys(_PATHS, "string")
    assert _types(document, "RulesOut") == dict.fromkeys(_PATHS, "string")


def test_a_component_two_seats_share_states_the_first_operation_s_rules() -> None:
    ruled = _created(_spec(SerializerValidator(RulesIn, json_schema_registry=SEAT)))
    bare = _created(_spec(SerializerValidator(RulesIn)))
    assert _types(_document(("a/", ruled), ("b/", bare)), "RulesIn")["code"] == "string"
    assert _types(_document(("a/", bare), ("b/", ruled)), "RulesIn")["code"] == "integer"


# -- What the fragment becomes -------------------------------------------------------


class MetaIn(serializers.Serializer):
    code = LooseIntField(allow_null=True, help_text="The order code.")
    shown = LooseIntField(read_only=True)


def _one(fragment: dict[str, Any], serializer: type = MetaIn) -> dict[str, Any]:
    seat = JsonSchemaRegistry(fields=((LooseIntField, fragment),))
    view = _created(
        _spec(
            SerializerValidator(serializer, json_schema_registry=seat),
            SerializerPresenter(serializer, json_schema_registry=seat),
        )
    )
    return _properties(_document(("o/", view)), serializer.__name__)


def test_the_field_s_own_meta_stands_beside_the_fragment() -> None:
    properties = _one({"type": "string", "description": "From the rule."})
    assert properties["code"] == {
        "type": "string",
        "nullable": True,
        "description": "The order code.",
    }
    assert properties["shown"] == {
        "type": "string",
        "description": "From the rule.",
        "readOnly": True,
    }


def test_a_nullable_type_list_is_stated_as_nullable() -> None:
    assert _one({"type": ["string", "null"]})["shown"] == {
        "type": "string",
        "nullable": True,
        "readOnly": True,
    }


def test_a_ref_the_document_cannot_resolve_is_dropped_and_named(warned: list[str]) -> None:
    fragment = {"type": "array", "items": {"$ref": "#/$defs/Code"}, "$defs": {"Code": {}}}
    assert _one(fragment)["shown"] == {"type": "array", "items": {}, "readOnly": True}
    assert len(warned) == 2
    assert all("LooseIntField" in each and "#/$defs/Code" in each for each in warned)
    assert {"'code'", "'shown'"} == {
        name for name in ("'code'", "'shown'") for w in warned if name in w
    }


def test_the_rest_of_the_fragment_is_kept() -> None:
    fragment = {"type": "string", "format": "money", "pattern": "^[A-Z]{2}-[0-9]+$"}
    assert _one(fragment)["shown"] == {**fragment, "readOnly": True}


class AnnotatedIn(serializers.Serializer):
    code = AnnotatedIntField()


def test_a_rule_wins_over_extend_schema_field() -> None:
    assert _one_annotated(None) == {"type": "boolean"}
    assert _one_annotated({"type": "string"}) == {"type": "string"}


def _one_annotated(fragment: dict[str, Any] | None) -> dict[str, Any]:
    rules = () if fragment is None else ((AnnotatedIntField, fragment),)
    validator = SerializerValidator(AnnotatedIn, json_schema_registry=JsonSchemaRegistry(rules))
    document = _document(("x/", _created(_spec(validator))))
    return _properties(document, "AnnotatedIn")["code"]


def test_a_property_named_like_a_dropped_keyword_is_kept(warned: list[str]) -> None:
    fragment = {
        "type": "object",
        "properties": {"definitions": {"$ref": "#/$defs/Code"}},
        "required": ["definitions"],
    }
    assert _one(fragment)["shown"] == {
        "type": "object",
        "properties": {"definitions": {}},
        "required": ["definitions"],
        "readOnly": True,
    }


class ExtendedIntField(serializers.IntegerField): ...


class _ExtendedIntFieldExtension(OpenApiSerializerFieldExtension):
    target_class = ExtendedIntField

    def map_serializer_field(self, auto_schema: Any, direction: Any) -> dict[str, Any]:
        return {"type": "boolean"}


class ExtendedIn(serializers.Serializer):
    code = ExtendedIntField()


def test_a_rule_wins_over_a_field_extension() -> None:
    def code(rules: tuple[Any, ...]) -> dict[str, Any]:
        validator = SerializerValidator(ExtendedIn, json_schema_registry=JsonSchemaRegistry(rules))
        return _properties(_document(("e/", _created(_spec(validator)))), "ExtendedIn")["code"]

    assert code(()) == {"type": "boolean"}
    assert code(((ExtendedIntField, {"type": "string"}),)) == {"type": "string"}


def test_a_seat_rule_types_a_row_documented_beside_its_affordances() -> None:
    spec = LISTING.derive(presenter=SerializerPresenter(RulesOut, json_schema_registry=SEAT))
    view = type("RulesLinked", (SelectorListView,), {"spec": spec}).as_view()
    document = _document(("a/", view))
    assert _types(document, "RulesOut") == dict.fromkeys(_PATHS, "string")


class NullableIn(serializers.Serializer):
    code = LooseIntField(allow_null=True)
    shown = LooseIntField(read_only=True)
    either = LooseIntField(allow_null=True, required=False)


def _nullable(version: str, fragment: dict[str, Any], name: str) -> dict[str, Any]:
    seat = JsonSchemaRegistry(fields=((LooseIntField, fragment),))
    view = _created(_spec(SerializerValidator(NullableIn, json_schema_registry=seat)))
    with patched_settings({"OAS_VERSION": version}):
        document = _document(("n/", view))
    validate_schema(document)
    return _properties(document, "NullableIn")[name]


def test_a_nullable_rule_on_a_nullable_field_states_null_once() -> None:
    fragment = {"type": ["string", "null"]}
    assert _nullable("3.0.3", fragment, "code") == {"type": "string", "nullable": True}
    assert _nullable("3.1.0", fragment, "code") == {"type": ["string", "null"]}
    assert _nullable("3.1.0", fragment, "shown") == {"type": ["string", "null"], "readOnly": True}


def test_a_rule_of_several_types_on_a_nullable_field_states_null_once_under_3_1() -> None:
    fragment = {"type": ["string", "integer", "null"]}
    assert _nullable("3.1.0", fragment, "either") == {"type": ["string", "integer", "null"]}


def test_a_rule_of_several_types_gains_null_on_a_nullable_field_alone_under_3_1() -> None:
    fragment = {"type": ["string", "integer"]}
    assert _nullable("3.1.0", fragment, "either") == {"type": ["string", "integer", "null"]}
    assert _nullable("3.1.0", fragment, "shown") == {
        "type": ["string", "integer"],
        "readOnly": True,
    }
