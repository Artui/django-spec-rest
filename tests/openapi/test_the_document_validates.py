"""The whole test app's document validates under OpenAPI 3.0 and 3.1, whatever the kernel writes.

The kernel's schemas are JSON Schema, which 3.1 is and 3.0, drf-spectacular's
default ``OAS_VERSION``, is not (no ``const``, no type list), so the document
spells them as ``nullable`` and ``enum`` under 3.0
(``lowered_for_the_document``, tested alone in test_lowered_for_the_document).
This generates every route of ``test_service_auto_schema``'s test app and of
``kernel_shapes`` (a nullable and a labelled field, in a request body, a
response body and a parameter), and holds that ``validate_schema`` accepts it.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.urls import URLPattern, URLResolver
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.settings import patched_settings
from drf_spectacular.validation import validate_schema

from django_spec_rest.openapi import enable_openapi, service_auto_schema
from tests.openapi import kernel_shapes
from tests.openapi.test_service_auto_schema import urlpatterns as the_test_app

_ROUTES: list[URLPattern | URLResolver] = [*the_test_app, *kernel_shapes.urlpatterns]
_AB = [{"const": "a", "title": "A"}, {"const": "b", "title": "B"}]


def _document(oas_version: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    enable_openapi()
    real = service_auto_schema.filter_set_parameters
    # The kernel at this package's floor writes a ``FilterSet``'s parameters
    # with no label and no null, so the shapes it writes later are fed to the
    # one filter that declares them.
    monkeypatch.setattr(
        service_auto_schema,
        "filter_set_parameters",
        lambda filter_set: (
            kernel_shapes.FILTER_PARAMETERS
            if filter_set is kernel_shapes.PostFilter
            else real(filter_set)
        ),
    )
    with patched_settings({"OAS_VERSION": oas_version}):
        return SchemaGenerator(patterns=_ROUTES).get_schema(request=None, public=True)


@pytest.fixture(params=["3.0.3", "3.1.0"])
def document(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return _document(request.param, monkeypatch)


@pytest.fixture
def document_3_0(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return _document("3.0.3", monkeypatch)


@pytest.fixture
def document_3_1(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return _document("3.1.0", monkeypatch)


def test_the_whole_document_validates(document: dict[str, Any]) -> None:
    validate_schema(document)


def _body(document: dict[str, Any], route: str, method: str) -> dict[str, Any]:
    content = document["paths"][route][method]["requestBody"]["content"]
    return content["application/json"]["schema"]


def _answer(document: dict[str, Any], route: str) -> dict[str, Any]:
    content = document["paths"][route]["get"]["responses"]["200"]["content"]
    return content["application/json"]["schema"]


def _parameter(document: dict[str, Any], route: str, name: str) -> dict[str, Any]:
    (found,) = [p for p in document["paths"][route]["get"]["parameters"] if p["name"] == name]
    return found["schema"]


class TestUnderOpenAPI3_0:
    def test_a_request_body_is_nullable_and_enum(self, document_3_0: dict[str, Any]) -> None:
        row = {
            "type": "object",
            "properties": {
                "maybe": {"type": "string", "nullable": True},
                "kind": {"type": "string", "enum": ["a", "b"]},
            },
        }
        assert _body(document_3_0, "/shapes/write/", "post") == {
            "type": "object",
            "properties": {
                "maybe": {"type": "string", "nullable": True},
                "kind": {"type": "string", "enum": ["a", "b"]},
                "maybe_kind": {"type": "string", "nullable": True, "enum": ["a", "b", None]},
                "plain": {"type": "string", "nullable": True, "enum": ["x", "y", None]},
                "tags": {
                    "type": "array",
                    "items": {"type": "string", "nullable": True, "enum": ["a", "b", None]},
                    "maxItems": 1000,
                },
                "rows": {"type": "array", "items": row, "maxItems": 1000},
                "nested": {
                    "type": "object",
                    "properties": {
                        "maybe_kind": {
                            "type": "string",
                            "nullable": True,
                            "enum": ["a", "b", None],
                        }
                    },
                },
            },
        }

    def test_a_many_spec_s_request_body_is_lowered_as_the_list_it_is(
        self, document_3_0: dict[str, Any]
    ) -> None:
        body = _body(document_3_0, "/shapes/write-many/", "post")
        assert body["type"] == "array"
        assert body["items"]["properties"]["maybe_kind"] == {
            "type": "string",
            "nullable": True,
            "enum": ["a", "b", None],
        }

    def test_a_response_body_is_nullable_and_enum(self, document_3_0: dict[str, Any]) -> None:
        item = _answer(document_3_0, "/shapes/read/")["items"]
        assert item["properties"] == {
            "maybe": {"type": "string", "nullable": True},
            "kind": {"type": "string", "enum": ["a", "b"]},
            "maybe_kind": {"type": "string", "nullable": True, "enum": ["a", "b", None]},
            "plain": {"type": "string", "nullable": True, "enum": ["x", "y", None]},
            "tags": {
                "type": "array",
                "items": {"type": "string", "nullable": True, "enum": ["a", "b", None]},
            },
            "scores": {"type": "array", "nullable": True, "items": {"type": "integer"}},
            "nested": {
                "type": "object",
                "nullable": True,
                "properties": {
                    "maybe": {"type": "string", "nullable": True},
                    "kind": {"type": "string", "enum": ["a", "b"]},
                },
                "required": ["maybe", "kind"],
            },
        }

    def test_a_route_capture_is_an_enum(self, document_3_0: dict[str, Any]) -> None:
        # drf-spectacular drops ``nullable`` (and ``default``) from a path
        # parameter's schema itself, since a captured segment is always there;
        # the ``None`` the lowering put in the enum stays, which validates.
        assert _parameter(document_3_0, "/shapes/by/{kind}/", "kind") == {
            "type": "string",
            "enum": ["a", "b", None],
        }

    def test_a_filter_is_nullable_and_enum(self, document_3_0: dict[str, Any]) -> None:
        route = "/shapes/filtered/"
        assert _parameter(document_3_0, route, "maybe") == {"type": "string", "nullable": True}
        assert _parameter(document_3_0, route, "kind") == {"type": "string", "enum": ["a", "b"]}
        assert _parameter(document_3_0, route, "maybe_kind") == {
            "type": "string",
            "nullable": True,
            "enum": ["a", "b", None],
        }
        assert _parameter(document_3_0, route, "o")["items"] == {
            "type": "string",
            "enum": ["a", "b"],
        }


class TestUnderOpenAPI3_1:
    """The schema as the kernel writes it, titles and type lists included."""

    def test_a_request_body_keeps_the_kernel_s_schema(self, document_3_1: dict[str, Any]) -> None:
        properties = _body(document_3_1, "/shapes/write/", "post")["properties"]
        assert properties["maybe"] == {"type": ["string", "null"]}
        assert properties["kind"] == {"type": "string", "anyOf": _AB}
        assert properties["maybe_kind"] == {
            "type": ["string", "null"],
            "anyOf": [*_AB, {"type": "null"}],
        }

    def test_a_response_body_keeps_the_kernel_s_schema(self, document_3_1: dict[str, Any]) -> None:
        properties = _answer(document_3_1, "/shapes/read/")["items"]["properties"]
        assert properties["maybe"] == {"type": ["string", "null"]}
        assert properties["kind"] == {"type": "string", "oneOf": _AB}
        assert properties["maybe_kind"] == {
            "type": ["string", "null"],
            "oneOf": [*_AB, {"const": None}],
        }

    def test_a_parameter_keeps_the_kernel_s_schema(self, document_3_1: dict[str, Any]) -> None:
        assert _parameter(document_3_1, "/shapes/by/{kind}/", "kind") == {
            "type": ["string", "null"],
            "anyOf": [*_AB, {"type": "null"}],
        }
        assert _parameter(document_3_1, "/shapes/filtered/", "o")["items"] == {
            "type": "string",
            "anyOf": _AB,
        }
