"""What a ``SerializerValidator``'s ``json_schema_registry`` enforces under the kernel's ``dispatch``.

A keyword a kernel field spells is checked as a built-in field's would be, by
the kernel's shape check before the serializer runs; a keyword left in
``json_schema_extra`` is advertised and not checked.

A selector's reads take no registry: a kernel spec declares each read as a
``Parameter`` with its own type, so the rule drfs read off a selector's Python
annotations (``python_types``) has nothing to type.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django_service_specs import ServiceSpec, Unrestricted
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from rest_framework import serializers

from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.types.json_schema_registry import JsonSchemaRegistry

pytestmark = pytest.mark.django_db


class _Count(serializers.Field):
    """A field DRF checks nothing about, so every refusal below is the rule's."""

    def to_internal_value(self, data: Any) -> Any:
        return data

    def to_representation(self, value: Any) -> Any:
        return value


class _In(serializers.Serializer):
    count = _Count()


def _service(*, data: Any) -> Any:
    return data["count"]


_REGISTRY = JsonSchemaRegistry(
    fields=((_Count, {"type": "integer", "minimum": 0, "multipleOf": 2}),),
)
_SERVICE = ServiceSpec(
    service=_service,
    permissions=(Unrestricted(),),
    validator=SerializerValidator(_In, json_schema_registry=_REGISTRY),
)


def _dispatch(arguments: dict[str, Any]) -> Any:
    return dispatch(_SERVICE, principal=AnonymousUser(), arguments=arguments)


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        pytest.param({"count": "x"}, "invalid", id="the-type"),
        pytest.param({"count": -1}, "min_value", id="the-bound"),
    ],
)
def test_a_keyword_a_field_spells_is_checked(arguments: dict[str, Any], code: str) -> None:
    with pytest.raises(InvalidArguments) as excinfo:
        _dispatch(arguments)

    # The kernel's shape check answers, before the serializer runs, with a
    # ``CodedMessage`` carrying DRF's code for the same mistake.
    (message,) = excinfo.value.detail["count"]
    assert message.code == code


def test_a_keyword_left_in_json_schema_extra_is_not_checked() -> None:
    # 5 is no multiple of 2: ``multipleOf`` is advertised, never enforced.
    assert _dispatch({"count": 5}).value == 5


def test_without_the_registry_the_field_checks_nothing() -> None:
    """The refusals above are the rule's: the same serializer with no registry takes both."""
    spec = ServiceSpec(
        service=_service, permissions=(Unrestricted(),), validator=SerializerValidator(_In)
    )

    for value in ("x", -1):
        assert dispatch(spec, principal=AnonymousUser(), arguments={"count": value}).value == value
