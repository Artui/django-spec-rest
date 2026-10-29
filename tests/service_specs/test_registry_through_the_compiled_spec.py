"""A ``json_schema_registry`` handed to the DRF seats reaches the kernel spec they serve.

A kernel spec declares its seats itself, so the registry is the seat's own
argument: ``SerializerValidator(..., json_schema_registry=)`` for the input,
``SerializerPresenter(..., json_schema_registry=)`` for the output. The
kernel's schema of the spec then states what the rule spells, less a format
outside the kernel's four.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from typing import Any

from django_service_specs import SelectorKind, SelectorSpec, ServiceSpec, Unrestricted
from django_service_specs.output.output import OutputField
from django_service_specs.parameters.parameters import Parameter
from django_service_specs.schema.parameters_schema import parameters_schema
from django_service_specs.schema.spec_output_schema import spec_output_schema
from django_service_specs.types.unknown_arguments import UnknownArguments
from rest_framework import serializers

from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.types.json_schema_registry import JsonSchemaRegistry


class _MoneyField(serializers.CharField): ...


class _In(serializers.Serializer):
    amount = _MoneyField()
    other = serializers.CharField(required=False)


class _Out(serializers.Serializer):
    amount = _MoneyField()


_MONEY = {"type": "string", "format": "money", "pattern": "^[0-9]+$"}
_REGISTRY = JsonSchemaRegistry(fields=((_MoneyField, _MONEY),))

_OPEN = (Unrestricted(),)


def _service(**_kwargs: Any) -> None: ...


def _select(**_kwargs: Any) -> None: ...


def _amount_parameter(spec: ServiceSpec) -> Parameter:
    parameter = spec.parameters().get("amount")
    assert parameter is not None
    return parameter


def _amount_field(presenter: Any) -> OutputField:
    (field,) = presenter.output()
    return field


def _service_spec(
    registry: JsonSchemaRegistry | None = _REGISTRY, *, input_serializer: type = _In
) -> ServiceSpec:
    return ServiceSpec(
        service=_service,
        permissions=_OPEN,
        validator=SerializerValidator(input_serializer, json_schema_registry=registry),
    )


def test_a_spec_s_input_fields_take_the_validator_s_rules() -> None:
    parameter = _amount_parameter(_service_spec())
    assert (parameter.type, parameter.format) == ("string", None)
    assert parameter.json_schema_extra == {"pattern": "^[0-9]+$"}


def test_the_kernel_s_schema_states_the_rule_but_for_the_dropped_format() -> None:
    schema = parameters_schema(
        _service_spec().parameters(), unknown_arguments=UnknownArguments.IGNORE
    )
    assert schema["properties"]["amount"] == {"type": "string", "pattern": "^[0-9]+$"}


def test_an_excluded_validator_keeps_its_rules() -> None:
    spec = ServiceSpec(
        service=_service,
        permissions=_OPEN,
        validator=SerializerValidator(
            _In, excluded=frozenset({"other"}), json_schema_registry=_REGISTRY
        ),
    )
    assert spec.parameters().get("other") is None
    assert _amount_parameter(spec).json_schema_extra == {"pattern": "^[0-9]+$"}


def test_a_spec_s_output_fields_take_the_presenter_s_rules() -> None:
    spec = SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=_select,
        permissions=_OPEN,
        presenter=SerializerPresenter(_Out, json_schema_registry=_REGISTRY),
    )
    field = _amount_field(spec.presenter)
    assert (field.type, field.format, field.json_schema_extra) == (
        "string",
        None,
        {"pattern": "^[0-9]+$"},
    )
    assert spec_output_schema(spec)["properties"]["amount"] == {
        "type": "string",
        "pattern": "^[0-9]+$",
    }


def test_each_seat_reads_only_its_own_registry() -> None:
    """The Validator's rules never reach the presenter's fields, nor the reverse."""
    spec = ServiceSpec(
        service=_service,
        permissions=_OPEN,
        validator=SerializerValidator(_In, json_schema_registry=_REGISTRY),
        presenter=SerializerPresenter(_Out),
    )
    assert _amount_parameter(spec).json_schema_extra == {"pattern": "^[0-9]+$"}
    assert _amount_field(spec.presenter).json_schema_extra is None
    assert _amount_parameter(_service_spec(None)).json_schema_extra is None


# A rule the kernel can state only part of: no type, so neither the format nor
# the bound has a seat on the declared field.
_PARTLY = JsonSchemaRegistry(
    fields=((_MoneyField, {"format": "date", "minimum": 1, "pattern": "^[0-9]+$"}),)
)


def test_a_rule_the_kernel_cannot_state_whole_still_declares() -> None:
    parameter = _amount_parameter(_service_spec(_PARTLY))
    assert (parameter.type, parameter.format, parameter.minimum) == ("any", None, None)
    assert parameter.json_schema_extra == {"pattern": "^[0-9]+$"}
    # An output field has no bound to set, so the bound is advertised there.
    field = _amount_field(SerializerPresenter(_Out, json_schema_registry=_PARTLY))
    assert (field.type, field.format) == ("any", None)
    assert field.json_schema_extra == {"minimum": 1, "pattern": "^[0-9]+$"}


@dataclasses.dataclass
class _Order:
    amount: Decimal


def test_a_dataclass_input_takes_a_rule_on_the_field_class_it_is_read_through() -> None:
    """A dataclass is read through its ``DataclassSerializer``'s fields, so a rule
    keyed on its Python type is not read, and one on the field class is."""
    by_type = JsonSchemaRegistry(python_types=((Decimal, {"type": "string", "pattern": "^1"}),))
    parameter = _amount_parameter(_service_spec(by_type, input_serializer=_Order))
    assert (parameter.format, parameter.json_schema_extra) == ("decimal", None)

    by_field = JsonSchemaRegistry(
        fields=((serializers.DecimalField, {"type": "string", "pattern": "^1"}),)
    )
    parameter = _amount_parameter(_service_spec(by_field, input_serializer=_Order))
    assert parameter.json_schema_extra == {"pattern": "^1"}
