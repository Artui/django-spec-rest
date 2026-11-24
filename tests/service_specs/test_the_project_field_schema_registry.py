from __future__ import annotations

from typing import Any

import pytest
from django.test import override_settings
from django_service_specs import ServiceSpec, Unrestricted
from django_service_specs.output.output import Output
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.schema.parameters_schema import parameters_schema
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.types.json_schema_registry import (
    JsonSchemaRegistry as KernelJsonSchemaRegistry,
)
from django_service_specs.types.unknown_arguments import UnknownArguments
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

import django_spec_rest
from django_spec_rest import ServiceCreateView
from django_spec_rest.service_specs.kernel_spec_variant import kernel_spec_variant
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.types.json_schema_registry import JsonSchemaRegistry

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_SETTING = "SERVICE_SPECS_FIELD_SCHEMA_REGISTRY"
_HERE = "tests.service_specs.test_the_project_field_schema_registry"


class LooseIntField(serializers.IntegerField):
    """An ``IntegerField`` that keeps what it is sent: a code such as ``AB-12``."""

    def to_internal_value(self, data: Any) -> Any:
        return data

    def to_representation(self, value: Any) -> Any:
        return value


class _Inner(serializers.Serializer):
    code = LooseIntField()


class _In(serializers.Serializer):
    code = LooseIntField()
    inner = _Inner(required=False)
    codes = serializers.ListField(child=LooseIntField(), required=False)
    rows = _Inner(many=True, required=False)
    listed = serializers.ListField(child=_Inner(), required=False)


PROJECT = KernelJsonSchemaRegistry(fields=((LooseIntField, {"type": "string"}),))
PROJECT_FOR_THE_BASE = KernelJsonSchemaRegistry(
    fields=((serializers.IntegerField, {"type": "boolean"}),)
)


def _project(name: str = "PROJECT") -> Any:
    return override_settings(**{_SETTING: f"{_HERE}.{name}"})


def _service(*, data: Any) -> Any:
    return data


def _spec(validator: SerializerValidator) -> ServiceSpec:
    return ServiceSpec(service=_service, permissions=_OPEN, validator=validator)


def _types(declared: Parameters | Output, prefix: str = "") -> dict[str, Any]:
    """Every ``LooseIntField``'s declared type, by its path through nesting and lists."""
    found: dict[str, Any] = {}
    for each in declared:
        path = f"{prefix}{each.name}"
        if each.fields is not None:
            found.update(_types(each.fields, f"{path}."))
        elif isinstance(each.items, Parameters | Output):
            found.update(_types(each.items, f"{path}[]."))
        elif each.items is not None:
            found[f"{path}[]"] = each.items
        else:
            found[path] = each.type
    return found


_PATHS = ("code", "inner.code", "codes[]", "rows[].code", "listed[].code")
_ALL_STRING = dict.fromkeys(_PATHS, "string")
_ALL_INTEGER = dict.fromkeys(_PATHS, "integer")
_ALL_NUMBER = dict.fromkeys(_PATHS, "number")


# -- The project's rules answer a seat with none ----------------------------------


@pytest.mark.django_db
def test_the_project_s_rule_types_the_field_and_the_body_reaches_the_serializer() -> None:
    """The intake repro: no seat registry, the project's rule types the field a string."""
    spec = _spec(SerializerValidator(_In))
    view = type("_View", (ServiceCreateView,), {"spec": spec}).as_view()
    refused = view(factory.post("/", {"code": "AB-12"}, format="json"))
    assert refused.status_code == 400
    assert [str(message) for message in refused.data["code"]] == ["Expected an integer."]
    with _project():
        schema = parameters_schema(spec.parameters(), unknown_arguments=UnknownArguments.IGNORE)
        assert schema["properties"]["code"]["type"] == "string"
        response = view(factory.post("/", {"code": "AB-12"}, format="json"))
    assert response.status_code == 201, response.data
    assert response.data == {"code": "AB-12"}


def test_the_project_s_rule_types_a_validator_s_fields_at_every_depth() -> None:
    with _project():
        assert _types(SerializerValidator(_In).parameters()) == _ALL_STRING


def test_the_project_s_rule_types_a_presenter_s_fields_at_every_depth() -> None:
    with _project():
        assert _types(SerializerPresenter(_In).output()) == _ALL_STRING


def test_without_the_setting_the_walk_is_the_table_s() -> None:
    assert _types(SerializerValidator(_In).parameters()) == _ALL_INTEGER
    assert _types(SerializerPresenter(_In).output()) == _ALL_INTEGER


# -- Precedence: the most specific class, then the seat ----------------------------


def test_the_project_s_rule_for_the_field_s_class_beats_the_seat_s_for_its_base() -> None:
    seat = JsonSchemaRegistry(fields=((serializers.IntegerField, {"type": "number"}),))
    with _project():
        assert _types(SerializerValidator(_In, json_schema_registry=seat).parameters()) == (
            _ALL_STRING
        )
        assert _types(SerializerPresenter(_In, json_schema_registry=seat).output()) == (_ALL_STRING)


def test_the_seat_s_rule_for_the_field_s_class_beats_the_project_s_for_its_base() -> None:
    seat = JsonSchemaRegistry(fields=((LooseIntField, {"type": "string"}),))
    with _project("PROJECT_FOR_THE_BASE"):
        assert _types(SerializerValidator(_In, json_schema_registry=seat).parameters()) == (
            _ALL_STRING
        )
        assert _types(SerializerPresenter(_In, json_schema_registry=seat).output()) == (_ALL_STRING)


def test_at_one_class_the_seat_s_rule_beats_the_project_s() -> None:
    seat = JsonSchemaRegistry(fields=((LooseIntField, {"type": "number"}),))
    with _project():
        assert (
            _types(SerializerValidator(_In, json_schema_registry=seat).parameters()) == _ALL_NUMBER
        )
        assert _types(SerializerPresenter(_In, json_schema_registry=seat).output()) == _ALL_NUMBER


def test_an_empty_seat_registry_still_reads_the_project_s() -> None:
    with _project():
        empty = JsonSchemaRegistry()
        assert _types(SerializerValidator(_In, json_schema_registry=empty).parameters()) == (
            _ALL_STRING
        )
        assert _types(SerializerPresenter(_In, json_schema_registry=empty).output()) == (
            _ALL_STRING
        )


def test_a_seat_s_own_rules_are_matched_by_the_most_specific_class_not_by_order() -> None:
    """A rule for a base listed first no longer answers a subclass with a rule of its own."""
    seat = JsonSchemaRegistry(
        fields=(
            (serializers.IntegerField, {"type": "number"}),
            (LooseIntField, {"type": "string"}),
        )
    )
    assert _types(SerializerValidator(_In, json_schema_registry=seat).parameters()) == (_ALL_STRING)
    assert _types(SerializerPresenter(_In, json_schema_registry=seat).output()) == (_ALL_STRING)


def test_a_rule_keyed_on_a_tuple_of_classes_matches_nothing() -> None:
    seat = JsonSchemaRegistry(
        fields=(((LooseIntField, serializers.CharField), {"type": "string"}),)
    )
    assert _types(SerializerValidator(_In, json_schema_registry=seat).parameters()) == (
        _ALL_INTEGER
    )
    assert _types(SerializerPresenter(_In, json_schema_registry=seat).output()) == _ALL_INTEGER


# -- The opt-out ------------------------------------------------------------------


def test_a_validator_opting_out_reads_no_project_rule_at_any_depth() -> None:
    with _project():
        validator = SerializerValidator(_In, project_registry=False)
        assert _types(validator.parameters()) == _ALL_INTEGER


def test_a_presenter_opting_out_reads_no_project_rule_at_any_depth() -> None:
    with _project():
        presenter = SerializerPresenter(_In, project_registry=False)
        assert _types(presenter.output()) == _ALL_INTEGER


def test_an_opted_out_seat_keeps_its_own_rules() -> None:
    seat = JsonSchemaRegistry(fields=((LooseIntField, {"type": "number"}),))
    with _project():
        validator = SerializerValidator(_In, json_schema_registry=seat, project_registry=False)
        presenter = SerializerPresenter(_In, json_schema_registry=seat, project_registry=False)
        assert _types(validator.parameters()) == _ALL_NUMBER
        assert _types(presenter.output()) == _ALL_NUMBER


# -- Read at the call --------------------------------------------------------------


def test_the_setting_reaches_a_spec_compiled_before_it() -> None:
    spec = _spec(SerializerValidator(_In))
    compiled = kernel_spec(spec)
    partial = kernel_spec_variant(spec, partial=True)
    assert _types(compiled.parameters()) == _ALL_INTEGER
    assert _types(partial.parameters()) == _ALL_INTEGER
    with _project():
        assert _types(kernel_spec_variant(spec).parameters()) == _ALL_STRING
        assert _types(kernel_spec_variant(spec, partial=True).parameters()) == _ALL_STRING
    assert _types(kernel_spec_variant(spec, partial=True).parameters()) == _ALL_INTEGER


@pytest.mark.parametrize("project_registry", [True, False])
def test_the_lenient_copy_keeps_the_seat_s_opt_out(project_registry: bool) -> None:
    spec = _spec(SerializerValidator(_In, project_registry=project_registry))
    lenient = kernel_spec_variant(spec, lenient=True)
    assert isinstance(lenient.validator, SerializerValidator)
    assert lenient.validator.lenient is True
    assert lenient.validator.project_registry is project_registry


# -- The type ---------------------------------------------------------------------


def test_the_registry_is_the_kernel_s_from_its_old_paths() -> None:
    assert JsonSchemaRegistry is KernelJsonSchemaRegistry
    assert django_spec_rest.JsonSchemaRegistry is KernelJsonSchemaRegistry
    assert isinstance(django_spec_rest.DEFAULT_JSON_SCHEMA_REGISTRY, KernelJsonSchemaRegistry)
    assert django_spec_rest.DEFAULT_JSON_SCHEMA_REGISTRY.fields == ()
