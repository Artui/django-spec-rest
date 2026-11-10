from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import URLPattern
from drf_spectacular.generators import SchemaGenerator
from rest_framework import serializers

from django_spec_rest.openapi import enable_openapi
from tests.openapi.reserved_names import SERIALIZERS, OuterSerializer, ours, theirs


def _generate(*patterns: URLPattern) -> dict[str, Any]:
    enable_openapi()
    return SchemaGenerator(patterns=list(patterns)).get_schema(request=None, public=True)


class TestAReservedName:
    @pytest.mark.parametrize("serializer", SERIALIZERS, ids=lambda cls: cls.__name__)
    def test_a_reserved_name_is_refused_on_drf_spectacular_s_schema(
        self, serializer: type[serializers.Serializer]
    ) -> None:
        """The package's refusal first: the hook refuses, naming the operation."""
        name = serializer.__name__.removesuffix("Serializer")
        with pytest.raises(ImproperlyConfigured) as raised:
            _generate(ours("a-ours"), theirs("b-theirs", serializer))
        message = str(raised.value)
        assert message.startswith(
            f"The operation POST /b-theirs/ is documented as the component {name!r}"
        )
        assert "component_name" in message

    @pytest.mark.parametrize("serializer", SERIALIZERS, ids=lambda cls: cls.__name__)
    def test_is_refused_when_the_project_s_view_comes_first(
        self, serializer: type[serializers.Serializer]
    ) -> None:
        """The project's serializer first: the package's own schema refuses it, naming the class."""
        with pytest.raises(ImproperlyConfigured) as raised:
            _generate(theirs("a-theirs", serializer), ours("b-ours"))
        assert str(raised.value).startswith(f"{serializer.__module__}.{serializer.__qualname__} ")
        assert "component_name" in str(raised.value)

    def test_is_refused_in_a_component_of_the_project_s(self) -> None:
        with pytest.raises(ImproperlyConfigured) as raised:
            _generate(ours("a-ours"), theirs("b-theirs", OuterSerializer))
        assert str(raised.value).startswith(
            "The component 'Outer' is documented as the component 'PermissionDenied'"
        )
