"""``_spelled_for_the_document``: a kernel parameter schema, spelled for the document's OpenAPI version.

Held end to end, through a whole document, by test_labelled_parameters.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from drf_spectacular.settings import patched_settings

from django_spec_rest.openapi.service_auto_schema import _spelled_for_the_document

_ANY_OF = [{"const": "a", "title": "A"}, {"const": "b", "title": "B"}]


@pytest.fixture
def oas_3_0() -> Iterator[None]:
    with patched_settings({"OAS_VERSION": "3.0.3"}):
        yield


@pytest.mark.usefixtures("oas_3_0")
class TestTheLowering:
    def test_constants_become_the_values_in_order_and_the_titles_are_dropped(self) -> None:
        schema = {"type": "string", "anyOf": [{"const": "b", "title": "B"}, {"const": "a"}]}
        assert _spelled_for_the_document(schema) == {"type": "string", "enum": ["b", "a"]}

    def test_the_schema_given_is_left_as_it_was(self) -> None:
        schema = {"type": "string", "anyOf": [{"const": "a", "title": "A"}]}
        _spelled_for_the_document(schema)
        assert schema == {"type": "string", "anyOf": [{"const": "a", "title": "A"}]}

    def test_an_array_s_items_are_lowered(self) -> None:
        schema = {"type": "array", "items": {"type": "string", "anyOf": _ANY_OF}, "maxItems": 3}
        assert _spelled_for_the_document(schema) == {
            "type": "array",
            "items": {"type": "string", "enum": ["a", "b"]},
            "maxItems": 3,
        }

    def test_a_schema_with_no_choices_is_as_it_was(self) -> None:
        schema = {"type": "array", "items": {"type": "integer"}}
        assert _spelled_for_the_document(schema) == schema
        assert _spelled_for_the_document({"type": "boolean"}) == {"type": "boolean"}

    def test_an_any_of_holding_anything_but_constants_stays(self) -> None:
        # Held without ``all``: each entry would pass, the null alone does not
        # (a mutant lowering on ``any`` drops the null and lets a null in).
        nullable = {"anyOf": [{"const": "a", "title": "A"}, {"type": "null"}]}
        assert _spelled_for_the_document(nullable) == nullable
        assert _spelled_for_the_document({"type": "array", "items": nullable}) == {
            "type": "array",
            "items": nullable,
        }

    def test_an_empty_any_of_stays(self) -> None:
        # ``all`` over nothing is true: without the emptiness test an empty
        # ``anyOf`` becomes an empty ``enum``, which admits no value.
        schema = {"type": "string", "anyOf": []}
        assert _spelled_for_the_document(schema) == schema

    @pytest.mark.parametrize("version", ["3.0.0", "3.0.3"])
    def test_every_3_0_is_lowered(self, version: str) -> None:
        with patched_settings({"OAS_VERSION": version}):
            assert _spelled_for_the_document({"anyOf": _ANY_OF}) == {"enum": ["a", "b"]}


@pytest.mark.parametrize("version", ["3.1.0", "3.2.0"])
def test_a_json_schema_document_keeps_the_any_of_and_its_titles(version: str) -> None:
    schema = {"type": "array", "items": {"type": "string", "anyOf": _ANY_OF}}
    with patched_settings({"OAS_VERSION": version}):
        assert _spelled_for_the_document(schema) == schema
