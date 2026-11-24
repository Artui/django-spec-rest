from __future__ import annotations

from typing import Any

import pytest
from django.urls import path
from django_service_specs import ServiceSpec, Unrestricted
from django_service_specs.schema.parameters_schema import parameters_schema
from drf_spectacular.generators import SchemaGenerator
from rest_framework import serializers

from django_spec_rest import ServiceCreateView
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.service_specs.serializer_validator import SerializerValidator

pytestmark = pytest.mark.django_db


class _Lengths(serializers.Serializer):
    title = serializers.CharField(max_length=100, min_length=2)
    email = serializers.EmailField(max_length=254)
    blank = serializers.CharField(max_length=10, min_length=2, allow_blank=True)


_VALIDATOR = SerializerValidator(_Lengths)
_SPEC = ServiceSpec(service=lambda **_: None, validator=_VALIDATOR, permissions=(Unrestricted(),))
urlpatterns = [path("lengths/", ServiceCreateView.as_view(spec=_SPEC))]


def _lengths(node: dict[str, Any]) -> dict[str, Any]:
    return {key: node[key] for key in ("maxLength", "minLength") if key in node}


def _documented() -> dict[str, Any]:
    enable_openapi()
    document = SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)
    body = document["paths"]["/lengths/"]["post"]["requestBody"]["content"]["application/json"]
    name = body["schema"]["$ref"].rsplit("/", 1)[-1]
    return document["components"]["schemas"][name]["properties"]


def test_the_document_and_the_compiled_spec_state_a_char_field_s_lengths_alike() -> None:
    """Where they part, an OpenAPI client and a page built from the spec read two bounds."""
    documented, compiled = _documented(), parameters_schema(_VALIDATOR.parameters())["properties"]
    for name in ("title", "email"):
        assert _lengths(documented[name]) == _lengths(compiled[name]), name


def test_a_blank_field_states_the_document_s_maximum_without_a_minimum() -> None:
    """drf-spectacular 0.27 states one node and later ones a blank alternative; both bound 10."""
    blank = _documented()["blank"]
    nodes = [_lengths(node) for node in blank.get("oneOf", [blank])]
    assert {"maxLength": 10, "minLength": 2} in nodes
    assert _lengths(parameters_schema(_VALIDATOR.parameters())["properties"]["blank"]) == {
        "maxLength": 10
    }
