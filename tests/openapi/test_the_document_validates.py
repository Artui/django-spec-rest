"""The test app's whole document validates under OpenAPI 3.0 and 3.1, for every kernel shape.

The kernel's schemas are JSON Schema, which 3.1 is and 3.0, drf-spectacular's
default ``OAS_VERSION``, is not (no ``const``, no type list), so the document
spells them as ``nullable`` and ``enum`` under 3.0
(``lowered_for_the_document``, tested alone in test_lowered_for_the_document).
This generates every route of ``test_service_auto_schema``'s test app and of
``kernel_shapes`` (a nullable and a labelled field, in a request body, a
response body, a route capture, a real ``FilterSet``'s query parameters and a
``DiscriminatedAction``'s request component), and holds that ``validate_schema``
accepts it. A schema an author writes by hand (``json_schema_extra``) is not
the kernel's and is not lowered: it reaches the document as written.
"""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest
from django.urls import URLPattern, URLResolver, path
from django_service_specs import (
    Output,
    OutputField,
    Presenter,
    SelectorKind,
    SelectorSpec,
    Unrestricted,
)
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.settings import patched_settings
from drf_spectacular.validation import validate_schema

from django_spec_rest import SelectorListView
from django_spec_rest.openapi import enable_openapi
from tests.openapi import kernel_shapes
from tests.openapi.test_service_auto_schema import urlpatterns as the_test_app

_ROUTES: list[URLPattern | URLResolver] = [*the_test_app, *kernel_shapes.urlpatterns]
_AB = [{"const": "a", "title": "A"}, {"const": "b", "title": "B"}]


def _document(oas_version: str) -> dict[str, Any]:
    enable_openapi()
    with patched_settings({"OAS_VERSION": oas_version}):
        return SchemaGenerator(patterns=_ROUTES).get_schema(request=None, public=True)


@pytest.fixture(params=["3.0.3", "3.1.0"])
def document(request: pytest.FixtureRequest) -> dict[str, Any]:
    return _document(request.param)


@pytest.fixture
def document_3_0() -> dict[str, Any]:
    return _document("3.0.3")


@pytest.fixture
def document_3_1() -> dict[str, Any]:
    return _document("3.1.0")


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
                # A null choice on a field whose ``type`` refuses null stays
                # non-nullable: the server answers 400 for a null.
                "closed": {"type": "string", "enum": [None, "a", "b"]},
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
            "closed": {"type": "string", "enum": [None, "a", "b"]},
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
        # the ``None`` the lowering put in the enum goes with it, since a
        # segment cannot be null.
        assert _parameter(document_3_0, "/shapes/by/{kind}/", "kind") == {
            "type": "string",
            "enum": ["a", "b"],
        }

    def test_a_real_filter_is_an_enum(self, document_3_0: dict[str, Any]) -> None:
        # The kernel's own ``filter_set_parameters`` for ``PostFilter``: a
        # choice filter, a multiple choice filter and an ordering filter, each
        # written with its labels (test_a_real_filter_keeps_its_labels).
        route = "/shapes/filtered/"
        assert _parameter(document_3_0, route, "kind") == {"type": "string", "enum": ["a", "b"]}
        assert _parameter(document_3_0, route, "several")["items"] == {
            "type": "string",
            "enum": ["a", "b"],
        }
        assert _parameter(document_3_0, route, "o")["items"] == {
            "type": "string",
            "enum": ["title", "-title", "id", "-id"],
        }

    def test_a_page_of_rows_is_lowered_once_under_results(
        self, document_3_0: dict[str, Any]
    ) -> None:
        results = _answer(document_3_0, "/shapes/paged/")["properties"]["results"]
        assert results["type"] == "array"
        assert results["items"]["properties"]["maybe_kind"] == {
            "type": "string",
            "nullable": True,
            "enum": ["a", "b", None],
        }
        assert results["items"]["properties"]["closed"] == {
            "type": "string",
            "enum": [None, "a", "b"],
        }

    def test_a_named_component_has_its_enum_moved_out_by_drf_spectacular(
        self, document_3_0: dict[str, Any]
    ) -> None:
        # Inside a registered component (a ``DiscriminatedAction``'s request),
        # drf-spectacular's ``postprocess_schema_enums`` moves the values to
        # ``*Enum`` components, as it does for a serializer's choice field, and
        # the nullable property reads them as a ``oneOf`` of two references.
        components = document_3_0["components"]["schemas"]
        kind = components["Chosen_create_Request"]["anyOf"][0]["properties"]["kind"]
        assert kind == {
            "nullable": True,
            "oneOf": [
                {"$ref": "#/components/schemas/KindEnum"},
                {"$ref": "#/components/schemas/NullEnum"},
            ],
        }
        assert components["KindEnum"] == {"type": "string", "enum": ["a", "b"]}
        assert components["NullEnum"] == {"enum": [None]}


class TestUnderOpenAPI3_1:
    """The schema as the kernel writes it, titles and type lists included."""

    def test_a_real_filter_keeps_its_labels(self, document_3_1: dict[str, Any]) -> None:
        # What the lowering takes away under 3.0, so the 3.0 test above is about
        # labels the kernel wrote and not a bare ``enum`` it passed through.
        route = "/shapes/filtered/"
        assert _parameter(document_3_1, route, "kind")["anyOf"] == [
            {"const": "a", "title": "A"},
            {"const": "b", "title": "B"},
        ]
        ordering = _parameter(document_3_1, route, "o")["items"]["anyOf"]
        assert [member["const"] for member in ordering] == ["title", "-title", "id", "-id"]
        assert all(member["title"] for member in ordering)

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

    def test_a_named_component_keeps_the_kernel_s_schema(
        self, document_3_1: dict[str, Any]
    ) -> None:
        kind = document_3_1["components"]["schemas"]["Chosen_create_Request"]["anyOf"][0]
        assert kind["properties"]["kind"] == {
            "type": ["string", "null"],
            "anyOf": [*_AB, {"type": "null"}],
        }
        assert not [name for name in document_3_1["components"]["schemas"] if name.endswith("Enum")]

    def test_a_parameter_keeps_the_kernel_s_schema(self, document_3_1: dict[str, Any]) -> None:
        assert _parameter(document_3_1, "/shapes/by/{kind}/", "kind") == {
            "type": ["string", "null"],
            "anyOf": [*_AB, {"type": "null"}],
        }
        # A real filter's choices, labelled by the kernel or not (the floor's
        # kernel writes none), are the kernel's as they are: never ``nullable``.
        kind = _parameter(document_3_1, "/shapes/filtered/", "kind")
        assert kind["type"] == "string"
        assert "nullable" not in kind


class _Extra(Presenter):
    """A presenter whose field carries what an author wrote in ``json_schema_extra``."""

    WRITTEN = {"anyOf": [{"type": "string"}, {"type": "null"}], "exclusiveMinimum": 0}

    def output(self) -> Output:
        return Output((OutputField("x", "any", json_schema_extra=self.WRITTEN),))

    def present(self, value: Any) -> Any:
        return value


def _extra_document(oas_version: str) -> dict[str, Any]:
    enable_openapi()
    view = type(
        "_Extra",
        (SelectorListView,),
        {
            "spec": SelectorSpec(
                kind=SelectorKind.LIST,
                selector=list,
                permissions=(Unrestricted(),),
                presenter=_Extra(),
            )
        },
    )
    with patched_settings({"OAS_VERSION": oas_version}):
        return SchemaGenerator(patterns=[path("extra/", view.as_view())]).get_schema(
            request=None, public=True
        )


def test_what_an_author_writes_in_json_schema_extra_reaches_the_document_as_written() -> None:
    # No kernel adapter writes these keys, so nothing here lowers them: under 3.0
    # a type list inside an ``anyOf``, ``exclusiveMinimum`` as a number and the
    # like are the author's to write as 3.0 reads them.
    document = _extra_document("3.0.3")

    item = _answer(document, "/extra/")["items"]
    assert item["properties"]["x"] == _Extra.WRITTEN
    with pytest.raises(jsonschema.ValidationError):
        validate_schema(document)
