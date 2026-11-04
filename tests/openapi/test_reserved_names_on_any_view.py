"""A component name the package documents a refusal by is refused on a view the package does not document.

``ValidationErrors``, ``PermissionDenied`` and ``NotAuthenticated`` are the
bodies of a spec's 400, 403 and 401. drf-spectacular keeps the first component
registered under a name and answers it for every later one with a warning only,
so a project's own view on drf-spectacular's ``AutoSchema`` resolving a
serializer of one of these names after the package's refusal would have its
request and response documented by the refusal's body. Each order is driven
for each name; only the public surface is imported, so the tests run against a
tree without the guard.
"""

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
    # drf-spectacular walks the paths in order: "a-" resolves before "b-".
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
        """The project's serializer first: the package's own schema refuses it, naming the class.

        The registry holds the project's serializer by then, so the package
        meets it while it documents its refusal, before the hook runs.
        """
        with pytest.raises(ImproperlyConfigured, match=serializer.__name__) as raised:
            _generate(theirs("a-theirs", serializer), ours("b-ours"))
        assert "component_name" in str(raised.value)

    def test_is_refused_in_a_component_of_the_project_s(self) -> None:
        with pytest.raises(ImproperlyConfigured) as raised:
            _generate(ours("a-ours"), theirs("b-theirs", OuterSerializer))
        assert str(raised.value).startswith(
            "The component 'Outer' is documented as the component 'PermissionDenied'"
        )
