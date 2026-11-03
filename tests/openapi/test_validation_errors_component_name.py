"""The ``ValidationErrors`` component is this schema's, and no serializer may take its name.

drf-spectacular only warns of two components of one name and keeps one for both,
so a serializer named ``ValidationErrorsSerializer`` would be documented by the
400's tree (or the 400 by the serializer's fields). Which of the two registers
first depends on the order drf-spectacular walks the paths, so each order is
driven.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import URLPattern, path
from django_service_specs import ServiceSpec, Unrestricted
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from django_spec_rest import ServiceCreateView
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer


class ValidationErrorsSerializer(serializers.Serializer):
    mine = serializers.CharField()


@extend_schema_serializer(component_name="RenamedErrors")
class _RenamedSerializer(ValidationErrorsSerializer): ...


def _store(*, data: Any = None, **_: Any) -> None: ...


def _route(prefix: str, *, validator: Any, presenter: Any) -> URLPattern:
    spec = ServiceSpec(
        service=_store,
        permissions=(Unrestricted(),),
        validator=validator,
        presenter=SerializerPresenter(presenter),
    )
    view = type("_View", (ServiceCreateView,), {"queryset": Author.objects.all(), "spec": spec})
    return path(f"{prefix}/", view.as_view())


def _refusing(prefix: str) -> URLPattern:
    return _route(
        prefix, validator=SerializerValidator(AuthorSerializer), presenter=AuthorSerializer
    )


def _named(prefix: str, presenter: Any = ValidationErrorsSerializer) -> URLPattern:
    return _route(prefix, validator=None, presenter=presenter)


def _generate(*patterns: URLPattern) -> dict[str, Any]:
    enable_openapi()
    return SchemaGenerator(patterns=list(patterns)).get_schema(request=None, public=True)


class TestASerializerTakingTheComponentName:
    # drf-spectacular walks the paths in order: "a-" resolves before "b-".
    @pytest.mark.parametrize(
        "patterns",
        [
            (_named("a-theirs"), _refusing("b-ours")),
            (_refusing("a-ours"), _named("b-theirs")),
        ],
        ids=["the serializer first", "the 400 first"],
    )
    def test_is_refused_whichever_comes_first(self, patterns: tuple[URLPattern, ...]) -> None:
        with pytest.raises(ImproperlyConfigured, match="ValidationErrorsSerializer") as raised:
            _generate(*patterns)
        assert "component_name" in str(raised.value)

    def test_is_documented_once_it_is_named_another_way(self) -> None:
        schema = _generate(_named("a-theirs", _RenamedSerializer), _refusing("b-ours"))
        schemas = schema["components"]["schemas"]
        assert schemas["RenamedErrors"]["properties"] == {"mine": {"type": "string"}}
        assert "mine" not in schemas["ValidationErrors"].get("properties", {})
