"""A labelled parameter, documented so the document validates under OpenAPI 3.0.

The kernel states a labelled choice as an ``anyOf`` of ``{"const", "title"}``,
under ``items`` for an array. OpenAPI 3.0, drf-spectacular's default
``OAS_VERSION``, has no ``const``, so ``validate_schema`` refused the whole
document. Under 3.0 the document spells the choices as an ``enum`` (the values,
in order; 3.0 has no place for the titles), and under 3.1 it keeps the
kernel's ``anyOf`` and its titles. A real filter's labels are held in
``test_the_document_validates``.
"""

from __future__ import annotations

from typing import Any

from django.urls import path
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    Unrestricted,
)
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.settings import patched_settings
from drf_spectacular.validation import validate_schema

from django_spec_rest import SelectorRetrieveView
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

_OPEN = (Unrestricted(),)
_LABELLED = {"choices": ["a", "b"], "choice_labels": {"a": "A", "b": "B"}}
_ANY_OF = [{"const": "a", "title": "A"}, {"const": "b", "title": "B"}]


def _retrieve(**choices: Any) -> Any:
    return type(
        "_ByKind",
        (SelectorRetrieveView,),
        {
            # No ``queryset``, so no model types the capture and the spec's read does.
            "spec": SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, kind: Author.objects.first(),
                reads=Parameters.of(
                    Parameter("kind", "string", required=True, **(choices or _LABELLED))
                ),
                permissions=_OPEN,
                presenter=SerializerPresenter(AuthorSerializer),
            ),
        },
    )


def _document(oas_version: str, *views: tuple[str, Any]) -> dict[str, Any]:
    enable_openapi()
    patterns = [path(route, view.as_view()) for route, view in views]
    with patched_settings({"OAS_VERSION": oas_version}):
        return SchemaGenerator(patterns=patterns).get_schema(request=None, public=True)


def _parameter(document: dict[str, Any], route: str, name: str) -> dict[str, Any]:
    (found,) = [p for p in document["paths"][route]["get"]["parameters"] if p["name"] == name]
    return found


class TestALabelledPathParameter:
    """A spec's labelled read on a route capture."""

    def test_it_is_an_enum_and_the_document_validates_under_3_0(self) -> None:
        document = _document("3.0.3", ("by/<kind>/", _retrieve()))
        validate_schema(document)
        assert _parameter(document, "/by/{kind}/", "kind")["schema"] == {
            "type": "string",
            "enum": ["a", "b"],
        }

    def test_it_keeps_its_titles_under_3_1(self) -> None:
        document = _document("3.1.0", ("by/<kind>/", _retrieve()))
        assert _parameter(document, "/by/{kind}/", "kind")["schema"] == {
            "type": "string",
            "anyOf": _ANY_OF,
        }
        validate_schema(document)

    def test_a_null_choice_is_no_value_of_a_segment(self) -> None:
        # A captured segment is always present. drf-spectacular drops ``nullable``
        # from a path parameter, so a ``null`` left in its ``enum`` would list a
        # value nothing can send.
        view = _retrieve(choices=["a", "b", None], choice_labels={"a": "A", "b": "B", None: "None"})
        document = _document("3.0.3", ("by/<kind>/", view))
        validate_schema(document)
        assert _parameter(document, "/by/{kind}/", "kind")["schema"] == {
            "type": "string",
            "enum": ["a", "b"],
        }

    def test_a_null_choice_is_no_value_of_a_segment_under_3_1_either(self) -> None:
        # The one place 3.1 is not the kernel's schema as written: the reason
        # is the segment, not the version.
        document = _document("3.1.0", ("by/<kind>/", _retrieve(choices=["a", "b", None])))
        validate_schema(document)
        assert _parameter(document, "/by/{kind}/", "kind")["schema"] == {
            "type": "string",
            "enum": ["a", "b"],
        }

    def test_an_enum_of_nothing_but_null_is_no_enum(self) -> None:
        # An ``enum`` of no value admits none; the segment is a plain string.
        document = _document("3.0.3", ("by/<kind>/", _retrieve(choices=[None])))
        validate_schema(document)
        assert _parameter(document, "/by/{kind}/", "kind")["schema"] == {"type": "string"}
