"""``lowered_for_the_document``: a kernel schema, written for the document's OpenAPI version.

The kernel's schemas are JSON Schema. OpenAPI 3.0, drf-spectacular's default
``OAS_VERSION``, is not: it has no ``const`` and no type list, so ``nullable``
and ``enum`` say what the kernel says with a type list, an ``anyOf`` or a
``oneOf``. Held end to end, through a whole document, by
test_the_document_validates.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from drf_spectacular.settings import patched_settings

from django_spec_rest.openapi._lowered_for_the_document import lowered_for_the_document

_TITLED = [{"const": "a", "title": "A"}, {"const": "b", "title": "B"}]

# Every shape the kernel writes that 3.0 spells otherwise: the schema as the
# kernel writes it, and as 3.0 reads it. The labelled ones are a parameter's
# ``anyOf`` with ``{"type": "null"}`` and an output field's ``oneOf`` with
# ``{"const": None}``.
SHAPES: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "nullable": (
        {"type": ["string", "null"]},
        {"type": "string", "nullable": True},
    ),
    "nullable array": (
        {"type": ["array", "null"], "items": {"type": "integer"}},
        {"type": "array", "nullable": True, "items": {"type": "integer"}},
    ),
    "enum with null": (
        {"type": ["string", "null"], "enum": ["x", "y", None]},
        {"type": "string", "nullable": True, "enum": ["x", "y", None]},
    ),
    "labelled": (
        {"type": "string", "anyOf": _TITLED},
        {"type": "string", "enum": ["a", "b"]},
    ),
    "labelled null": (
        {"type": ["string", "null"], "anyOf": [*_TITLED, {"type": "null"}]},
        {"type": "string", "nullable": True, "enum": ["a", "b", None]},
    ),
    "labelled one of": (
        {"type": "string", "oneOf": _TITLED},
        {"type": "string", "enum": ["a", "b"]},
    ),
    "labelled one of null": (
        {"type": ["string", "null"], "oneOf": [*_TITLED, {"const": None}]},
        {"type": "string", "nullable": True, "enum": ["a", "b", None]},
    ),
}

# A shape placed where a kernel schema carries one, and the same placed in the
# lowered schema.
POSITIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "top": lambda schema: schema,
    "under properties": lambda schema: {
        "type": "object",
        "properties": {"field": schema},
        "required": ["field"],
    },
    "under items": lambda schema: {"type": "array", "items": schema, "maxItems": 3},
    "under additionalProperties": lambda schema: {
        "type": "object",
        "additionalProperties": schema,
    },
    "under a row": lambda schema: {
        "type": "array",
        "items": {"type": "object", "properties": {"field": schema}},
    },
    "under an allOf member": lambda schema: {"allOf": [schema, {"type": "object"}]},
    "under an anyOf of schemas": lambda schema: {"anyOf": [schema, {"type": "object"}]},
    "under a oneOf of schemas": lambda schema: {"oneOf": [{"type": "object"}, schema]},
}


@pytest.fixture
def oas_3_0() -> Iterator[None]:
    with patched_settings({"OAS_VERSION": "3.0.3"}):
        yield


@pytest.mark.usefixtures("oas_3_0")
class TestEveryShapeInEveryPosition:
    @pytest.mark.parametrize("shape", SHAPES)
    @pytest.mark.parametrize("position", POSITIONS)
    def test_it_is_lowered_where_it_stands(self, shape: str, position: str) -> None:
        kernel, lowered = SHAPES[shape]
        place = POSITIONS[position]
        assert lowered_for_the_document(place(kernel)) == place(lowered)

    @pytest.mark.parametrize("shape", SHAPES)
    @pytest.mark.parametrize("position", POSITIONS)
    def test_the_schema_given_is_not_modified(self, shape: str, position: str) -> None:
        schema = POSITIONS[position](copy.deepcopy(SHAPES[shape][0]))
        before = copy.deepcopy(schema)
        lowered_for_the_document(schema)
        assert schema == before

    def test_a_shape_nested_in_a_shape_is_lowered(self) -> None:
        kernel = {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": ["string", "null"], "oneOf": [*_TITLED, {"const": None}]}
                },
            },
        }
        assert lowered_for_the_document(kernel) == {
            "type": "array",
            "nullable": True,
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "nullable": True, "enum": ["a", "b", None]}
                },
            },
        }


@pytest.mark.usefixtures("oas_3_0")
class TestTheNullableType:
    @pytest.mark.parametrize("kind", [["string", "null"], ["null", "string"]])
    def test_a_type_and_null_is_the_type_made_nullable(self, kind: list[str]) -> None:
        assert lowered_for_the_document({"type": kind}) == {"type": "string", "nullable": True}

    @pytest.mark.parametrize(
        "kind",
        [
            "string",
            ["string"],
            ["string", "integer"],
            ["string", "integer", "null"],
            ["string", "null", "null"],
            ["null", "null"],
            [],
        ],
    )
    def test_any_other_type_is_as_it_was(self, kind: Any) -> None:
        # ``isinstance`` (a string is not a list), and each operand of the
        # list's reading: the length of two (["string"] is not nullable), and
        # exactly one type beside the null (["string", "integer"] has no null,
        # and ["null", "null"] no type).
        assert lowered_for_the_document({"type": kind}) == {"type": kind}

    def test_a_schema_with_no_type_is_as_it_was(self) -> None:
        assert lowered_for_the_document({"format": "uuid"}) == {"format": "uuid"}


@pytest.mark.usefixtures("oas_3_0")
class TestTheConstants:
    @pytest.mark.parametrize("keyword", ["anyOf", "oneOf"])
    def test_constants_become_the_values_in_order_and_the_titles_are_dropped(
        self, keyword: str
    ) -> None:
        schema = {"type": "string", keyword: [{"const": "b", "title": "B"}, {"const": "a"}]}
        assert lowered_for_the_document(schema) == {"type": "string", "enum": ["b", "a"]}

    @pytest.mark.parametrize("nothing", [{"type": "null"}, {"const": None}])
    def test_a_null_is_a_constant_of_null_and_makes_the_schema_nullable(
        self, nothing: dict[str, Any]
    ) -> None:
        schema = {"type": "string", "anyOf": [{"const": "a"}, nothing]}
        assert lowered_for_the_document(schema) == {
            "type": "string",
            "nullable": True,
            "enum": ["a", None],
        }

    def test_a_titled_null_is_a_constant_too(self) -> None:
        schema = {"type": "string", "anyOf": [{"const": "a"}, {"type": "null", "title": "None"}]}
        assert lowered_for_the_document(schema) == {
            "type": "string",
            "nullable": True,
            "enum": ["a", None],
        }

    def test_a_schema_made_nullable_by_its_type_and_its_constants_is_so_once(self) -> None:
        schema = {"type": ["string", "null"], "anyOf": [{"const": "a"}, {"type": "null"}]}
        assert lowered_for_the_document(schema) == {
            "type": "string",
            "nullable": True,
            "enum": ["a", None],
        }

    def test_constants_without_a_null_do_not_make_it_nullable(self) -> None:
        # A constant of ``false`` or ``0`` is no null: the test is ``is None``.
        schema = {"type": "integer", "anyOf": [{"const": 0}, {"const": 1}]}
        assert lowered_for_the_document(schema) == {"type": "integer", "enum": [0, 1]}

    def test_every_other_key_of_the_schema_stays(self) -> None:
        schema = {"type": "string", "description": "d", "default": "a", "anyOf": _TITLED}
        assert lowered_for_the_document(schema) == {
            "type": "string",
            "description": "d",
            "default": "a",
            "enum": ["a", "b"],
        }

    def test_an_empty_one_stays(self) -> None:
        # ``all`` over nothing is true: without the emptiness test an empty
        # ``anyOf`` becomes an empty ``enum``, which admits no value.
        for keyword in ("anyOf", "oneOf"):
            schema = {"type": "string", keyword: []}
            assert lowered_for_the_document(schema) == schema

    def test_one_holding_anything_but_constants_stays_and_its_members_are_walked(self) -> None:
        # ``all``, not ``any``: the constant alone would pass, the object does
        # not, and an ``enum`` of the constants would refuse the object.
        schema = {
            "anyOf": [
                {"const": "a", "title": "A"},
                {"type": ["object", "null"], "properties": {"n": {"type": ["integer", "null"]}}},
            ]
        }
        assert lowered_for_the_document(schema) == {
            "anyOf": [
                {"const": "a", "title": "A"},
                {
                    "type": "object",
                    "nullable": True,
                    "properties": {"n": {"type": "integer", "nullable": True}},
                },
            ]
        }

    @pytest.mark.parametrize(
        "member",
        [
            {"description": "no value"},
            {"type": "string"},
            {"type": "null", "description": "d"},
            {"const": "a", "description": "d"},
            {"const": "a", "type": "string"},
            {},
        ],
    )
    def test_a_member_stating_more_than_a_value_and_its_title_keeps_the_keyword(
        self, member: dict[str, Any]
    ) -> None:
        # Lowering it would drop what it states.
        schema = {"anyOf": [{"const": "x"}, member]}
        assert lowered_for_the_document(schema) == schema

    def test_members_that_are_no_list_keep_the_keyword(self) -> None:
        # A JSON list only: a tuple is data of another shape, left as it was.
        schema = {"anyOf": ({"const": "x"},)}
        assert lowered_for_the_document(schema) == schema

    def test_a_member_that_is_no_mapping_keeps_the_keyword(self) -> None:
        schema = {"anyOf": [{"const": "x"}, True]}
        assert lowered_for_the_document(schema) == schema

    def test_an_enum_already_there_is_never_replaced(self) -> None:
        schema = {"type": "string", "enum": ["z"], "anyOf": _TITLED}
        assert lowered_for_the_document(schema) == schema

    def test_one_keyword_is_lowered_when_the_other_holds_schemas(self) -> None:
        schema = {"oneOf": _TITLED, "anyOf": [{"type": "object"}, {"type": "array"}]}
        assert lowered_for_the_document(schema) == {
            "enum": ["a", "b"],
            "anyOf": [{"type": "object"}, {"type": "array"}],
        }


@pytest.mark.usefixtures("oas_3_0")
class TestWhatIsNeverRewritten:
    """A value is data, not a schema, whatever it looks like."""

    LOOKS_LIKE_A_SCHEMA = {
        "type": ["string", "null"],
        "anyOf": [{"const": "a", "title": "A"}],
        "items": {"type": ["integer", "null"]},
        "properties": {"type": {"type": ["string", "null"]}},
    }

    @pytest.mark.parametrize("keyword", ["default", "const", "example"])
    def test_a_value_a_keyword_holds(self, keyword: str) -> None:
        schema = {"type": "object", keyword: copy.deepcopy(self.LOOKS_LIKE_A_SCHEMA)}
        assert lowered_for_the_document(schema) == schema

    @pytest.mark.parametrize("keyword", ["enum", "examples"])
    def test_the_values_a_list_keyword_holds(self, keyword: str) -> None:
        schema = {"type": "object", keyword: [copy.deepcopy(self.LOOKS_LIKE_A_SCHEMA)]}
        assert lowered_for_the_document(schema) == schema

    def test_a_default_beneath_a_property_is_left_whole(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "field": {
                    "type": ["object", "null"],
                    "default": copy.deepcopy(self.LOOKS_LIKE_A_SCHEMA),
                }
            },
        }
        assert lowered_for_the_document(schema) == {
            "type": "object",
            "properties": {
                "field": {
                    "type": "object",
                    "nullable": True,
                    "default": self.LOOKS_LIKE_A_SCHEMA,
                }
            },
        }

    def test_a_property_named_for_a_keyword_is_a_property(self) -> None:
        # ``properties`` is a mapping of names to schemas, not a schema: a
        # property called ``type``, ``items`` or ``anyOf`` is read as the
        # schema it holds and its name is left alone.
        schema = {
            "type": "object",
            "properties": {
                "type": {"type": ["string", "null"]},
                "items": {"type": ["integer", "null"]},
                "anyOf": {"type": "string", "anyOf": _TITLED},
                "enum": {"type": "string"},
                "properties": {"type": ["string", "null"]},
            },
        }
        assert lowered_for_the_document(schema) == {
            "type": "object",
            "properties": {
                "type": {"type": "string", "nullable": True},
                "items": {"type": "integer", "nullable": True},
                "anyOf": {"type": "string", "enum": ["a", "b"]},
                "enum": {"type": "string"},
                "properties": {"type": "string", "nullable": True},
            },
        }

    @pytest.mark.parametrize("closed", [True, False])
    def test_an_additional_properties_that_is_no_mapping_is_as_it_was(self, closed: bool) -> None:
        schema = {"type": "object", "additionalProperties": closed}
        assert lowered_for_the_document(schema) == schema

    def test_items_that_are_no_mapping_are_as_they_were(self) -> None:
        schema = {"type": "array", "items": [{"type": ["string", "null"]}]}
        assert lowered_for_the_document(schema) == schema

    def test_properties_that_are_no_mapping_are_as_they_were(self) -> None:
        schema = {"type": "object", "properties": None}
        assert lowered_for_the_document(schema) == schema

    def test_a_property_that_is_no_mapping_is_as_it_was(self) -> None:
        schema = {"type": "object", "properties": {"field": True}}
        assert lowered_for_the_document(schema) == schema


@pytest.mark.usefixtures("oas_3_0")
def test_every_3_0_is_lowered() -> None:
    for version in ("3.0.0", "3.0.3"):
        with patched_settings({"OAS_VERSION": version}):
            assert lowered_for_the_document({"type": ["string", "null"]}) == {
                "type": "string",
                "nullable": True,
            }


@pytest.mark.parametrize("version", ["3.1.0", "3.2.0"])
@pytest.mark.parametrize("shape", SHAPES)
def test_a_json_schema_document_keeps_the_schema_as_the_kernel_writes_it(
    version: str, shape: str
) -> None:
    schema = POSITIONS["under items"](SHAPES[shape][0])
    with patched_settings({"OAS_VERSION": version}):
        assert lowered_for_the_document(schema) is schema
