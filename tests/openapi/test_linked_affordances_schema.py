from __future__ import annotations

from typing import Any

import jsonschema
import pytest
from django.test import Client
from django.urls import path
from django_service_specs import Output, OutputField, Presenter
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.settings import patched_settings
from drf_spectacular.validation import validate_schema

from django_spec_rest import SelectorListView
from django_spec_rest.openapi import enable_openapi
from tests.testapp.models import Post
from tests.views import linked_urls
from tests.views.linked_views import LISTING, ROUTES

_LINKED = {"rename", "publish", "archive", "nowhere", "stray", "flag"}


def _document(oas_version: str) -> dict[str, Any]:
    enable_openapi()
    with patched_settings({"OAS_VERSION": oas_version}):
        return SchemaGenerator(patterns=linked_urls.urlpatterns).get_schema(
            request=None, public=True
        )


@pytest.fixture(params=["3.0.3", "3.1.0"])
def document(request: pytest.FixtureRequest) -> dict[str, Any]:
    return _document(request.param)


def _answer(document: dict[str, Any], route: str) -> dict[str, Any]:
    content = document["paths"][route]["get"]["responses"]["200"]["content"]
    return {**content["application/json"]["schema"], "components": document["components"]}


def _entries(document: dict[str, Any], route: str) -> dict[str, Any]:
    answer = _answer(document, route)
    item = answer["items"] if answer.get("type") == "array" else answer
    return item["allOf"][1]["properties"]["affordances"]["properties"]


def test_the_document_validates(document: dict[str, Any]) -> None:
    validate_schema(document)


@pytest.mark.parametrize("route", ["/linked/", "/linked/{id}/", "/posts/", "/posts/{id}/"])
def test_a_named_target_s_entry_documents_href_and_method(
    document: dict[str, Any], route: str
) -> None:
    entries = _entries(document, route)
    assert {name for name, entry in entries.items() if "href" in entry["properties"]} == _LINKED
    assert entries["rename"]["required"] == ["available"]
    assert entries["rename"]["properties"]["method"]["enum"] == [
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    ]
    assert entries["publish"]["properties"]["code"]["enum"] == ["already_published"]


def test_no_link_routes_documents_the_answers_alone(document: dict[str, Any]) -> None:
    entries = _entries(document, "/unlinked/")
    assert not any("href" in entry["properties"] for entry in entries.values())
    assert set(entries) == {*_LINKED, "unnamed"}


@pytest.mark.django_db
@pytest.mark.parametrize("route", ["/linked/", "/posts/"])
def test_a_served_body_matches_its_document(route: str, settings: Any) -> None:
    settings.ROOT_URLCONF = linked_urls.__name__
    Post.objects.create(title="draft")
    Post.objects.create(title="out", published=True)
    document = _document("3.1.0")
    body = Client().get(route).json()
    jsonschema.validate(body, _answer(document, route))


class _Declared(Presenter):
    def output(self) -> Output | None:
        return Output((OutputField("id", "integer"),))

    def present(self, value: Any) -> Any:
        return {"id": value.pk}


class _Undeclared(_Declared):
    def output(self) -> Output | None:
        return None


@pytest.mark.parametrize(
    ("presenter", "documented"), [(_Declared(), True), (_Undeclared(), False)], ids=["out", "none"]
)
def test_a_presenter_s_output_is_the_row_s_schema(presenter: Presenter, documented: bool) -> None:
    enable_openapi()
    view = SelectorListView.as_view(spec=LISTING.derive(presenter=presenter), link_routes=ROUTES)
    document = SchemaGenerator(patterns=[path("rows/", view)]).get_schema(request=None, public=True)
    answer = _answer(document, "/rows/")
    if not documented:
        assert "items" not in answer
        return
    first, second = answer["items"]["allOf"]
    assert first["properties"]["id"] == {"type": "integer"}
    assert second["properties"]["affordances"]["properties"]["rename"]["properties"]["href"]


def test_a_serializer_row_references_its_component(document: dict[str, Any]) -> None:
    item = _answer(document, "/linked/")["items"]
    assert item["allOf"][0] == {"$ref": "#/components/schemas/PostOut"}
