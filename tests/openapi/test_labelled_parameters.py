"""A labelled parameter, documented so the document validates under OpenAPI 3.0.

The kernel states a labelled choice as an ``anyOf`` of ``{"const", "title"}``,
under ``items`` for an array. OpenAPI 3.0, drf-spectacular's default
``OAS_VERSION``, has no ``const``, so ``validate_schema`` refused the whole
document. Under 3.0 the document spells the choices as an ``enum`` (the values,
in order; 3.0 has no place for the titles), and under 3.1 it keeps the
kernel's ``anyOf`` and its titles.
"""

from __future__ import annotations

from typing import Any

import django_filters
import pytest
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

from django_spec_rest import SelectorListView, SelectorRetrieveView
from django_spec_rest.openapi import enable_openapi, service_auto_schema
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Author, Post
from tests.testapp.serializers import AuthorSerializer

_OPEN = (Unrestricted(),)
_LABELLED = {"choices": ["a", "b"], "choice_labels": {"a": "A", "b": "B"}}
_ANY_OF = [{"const": "a", "title": "A"}, {"const": "b", "title": "B"}]


class _PostFilter(django_filters.FilterSet):
    class Meta:
        model = Post
        fields: list[str] = []


def _retrieve() -> Any:
    return type(
        "_ByKind",
        (SelectorRetrieveView,),
        {
            # No ``queryset``, so no model types the capture and the spec's read does.
            "spec": SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, kind: Author.objects.first(),
                reads=Parameters.of(Parameter("kind", "string", required=True, **_LABELLED)),
                permissions=_OPEN,
                presenter=SerializerPresenter(AuthorSerializer),
            ),
        },
    )


def _list() -> Any:
    return type(
        "_Posts",
        (SelectorListView,),
        {
            "queryset": Post.objects.all(),
            "spec": SelectorSpec(
                kind=SelectorKind.LIST,
                selector=lambda: Post.objects.all(),
                permissions=_OPEN,
                presenter=SerializerPresenter(AuthorSerializer),
                filter_set=_PostFilter,
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
    """A spec's labelled read on a route capture (the kernel 0.30 reaches this today)."""

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


class TestALabelledFilter:
    """A FilterSet's parameters are the kernel's: the next kernel labels a
    ``ChoiceFilter`` and gives an ``OrderingFilter`` its choices, so this feeds
    ``_kernel_filter_parameters`` that shape, as the kernel's own ``Parameter``s."""

    @pytest.fixture(autouse=True)
    def _labelled_filters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            service_auto_schema,
            "filter_set_parameters",
            lambda filter_set: Parameters.of(
                Parameter("kind", "string", **_LABELLED),
                Parameter("o", "array", items="string", **_LABELLED),
            ),
        )

    def test_a_choice_and_an_ordering_are_enums_and_the_document_validates_under_3_0(
        self,
    ) -> None:
        document = _document("3.0.3", ("posts/", _list()))
        validate_schema(document)
        assert _parameter(document, "/posts/", "kind")["schema"] == {
            "type": "string",
            "enum": ["a", "b"],
        }
        assert _parameter(document, "/posts/", "o")["schema"]["items"] == {
            "type": "string",
            "enum": ["a", "b"],
        }

    def test_they_keep_their_titles_under_3_1(self) -> None:
        document = _document("3.1.0", ("posts/", _list()))
        assert _parameter(document, "/posts/", "kind")["schema"]["anyOf"] == _ANY_OF
        assert _parameter(document, "/posts/", "o")["schema"]["items"]["anyOf"] == _ANY_OF
        validate_schema(document)
