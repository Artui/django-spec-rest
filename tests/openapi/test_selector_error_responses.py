"""What a selector operation documents for a refused read, against what the edge sends.

A selector's parameters (its ``reads`` and ``shapes``, filters included) are
read off the query string and refused with DRF's field errors under a ``400``,
the same body a service spec's Validator answers; and a selector, a
precondition or a provider can raise a plain ``ServiceError``, a ``422``. Each
test drives the view, then validates the wire body against the schema the
operation documents for that status.
"""

from __future__ import annotations

import json
from typing import Any

import jsonschema
import pytest
from django.urls import path
from django_service_specs import (
    AdditionalInputRequired,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceError,
    Unrestricted,
)
from drf_spectacular.generators import SchemaGenerator
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorListView, SelectorRetrieveView
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Post

_OPEN = (Unrestricted(),)
_ASK_SCHEMA: dict[str, Any] = {"confirmed": {"type": "boolean", "default": False}}


class _PostOut(serializers.Serializer):
    title = serializers.CharField()


def _posts(**_: Any) -> Any:
    return Post.objects.none()


def _unprocessable(**_: Any) -> Any:
    raise ServiceError("Could not.")


def _asking(**_: Any) -> Any:
    raise AdditionalInputRequired("Say which.", schema=_ASK_SCHEMA)


def _spec(selector: Any, *, kind: SelectorKind = SelectorKind.LIST, **fields: Any) -> SelectorSpec:
    return SelectorSpec(
        **{
            "kind": kind,
            "selector": selector,
            "permissions": _OPEN,
            "presenter": SerializerPresenter(_PostOut),
            **fields,
        }
    )


_PUBLISHED = Parameters.of(Parameter("published", "boolean", required=True))
_ROWS = Parameters.of(Parameter("pk", "integer", required=True))

# Each route: its view, its spec, and the URL it is mounted at.
_SPECS: dict[str, tuple[type, SelectorSpec]] = {
    "read": (SelectorListView, _spec(_posts, reads=_PUBLISHED)),
    "unprocessable": (SelectorListView, _spec(_unprocessable)),
    "asking": (SelectorListView, _spec(_asking)),
    "no-reads": (SelectorListView, _spec(_posts)),
    "captured": (
        SelectorRetrieveView,
        _spec(_unprocessable, kind=SelectorKind.RETRIEVE, reads=_ROWS),
    ),
}

urlpatterns = [
    path(
        f"{key}/<int:pk>/" if key == "captured" else f"{key}/",
        type("_View", (view,), {"spec": spec}).as_view(),
    )
    for key, (view, spec) in _SPECS.items()
]


@pytest.fixture(scope="module", autouse=True)
def _enable_openapi() -> None:
    enable_openapi()


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)


def _responses(schema: dict[str, Any], key: str) -> dict[str, Any]:
    route = f"/{key}/{{id}}/" if key == "captured" else f"/{key}/"
    return schema["paths"][route]["get"]["responses"]


def _documented(schema: dict[str, Any], key: str, status: str) -> dict[str, Any]:
    body = _responses(schema, key)[status]["content"]["application/json"]["schema"]
    return {**body, "components": schema["components"]}


def _get(key: str, query: str = "") -> tuple[int, Any]:
    view = urlpatterns[list(_SPECS).index(key)].callback
    kwargs = {"pk": 1} if key == "captured" else {}
    response = view(APIRequestFactory().get(f"/{query}"), **kwargs)
    response.render()
    return response.status_code, json.loads(response.content)


@pytest.mark.django_db
class TestARefusedReadIsA400:
    @pytest.mark.parametrize("query", ["", "?published=maybe"])
    def test_the_documented_400_describes_the_body_the_edge_sends(
        self, schema: dict[str, Any], query: str
    ) -> None:
        status, sent = _get("read", query)
        assert status == 400
        assert list(sent) == ["published"]
        jsonschema.validate(sent, _documented(schema, "read", "400"))

    def test_it_is_the_component_a_service_spec_s_validator_documents(
        self, schema: dict[str, Any]
    ) -> None:
        assert "ValidationErrors" in json.dumps(_responses(schema, "read")["400"])

    def test_a_selector_with_no_parameter_documents_no_400_and_is_sent_none(
        self, schema: dict[str, Any]
    ) -> None:
        assert _get("no-reads", "?nope=1")[0] == 200
        assert "400" not in _responses(schema, "no-reads")

    def test_a_route_capture_alone_is_no_query_parameter_to_refuse(
        self, schema: dict[str, Any]
    ) -> None:
        assert "400" not in _responses(schema, "captured")

    def test_the_success_response_is_kept(self, schema: dict[str, Any]) -> None:
        documented = _documented(schema, "read", "200")
        assert documented["type"] == "array"
        assert _get("read", "?published=true") == (200, [])


@pytest.mark.django_db
class TestA422IsASelectorRefusal:
    @pytest.mark.parametrize("key", list(_SPECS))
    def test_it_is_documented_whatever_the_selector_reads(
        self, schema: dict[str, Any], key: str
    ) -> None:
        assert "422" in _responses(schema, key)

    @pytest.mark.parametrize("key", ["unprocessable", "captured"])
    def test_the_documented_422_describes_the_body_the_edge_sends(
        self, schema: dict[str, Any], key: str
    ) -> None:
        status, sent = _get(key)
        assert (status, sent) == (422, {"detail": "Could not."})
        jsonschema.validate(sent, _documented(schema, key, "422"))

    def test_an_additional_input_required_names_the_schema_it_carries(
        self, schema: dict[str, Any]
    ) -> None:
        status, sent = _get("asking")
        assert status == 422
        assert sent["detail"] == "Say which."
        # The schema's own leaves are not asserted: a standalone selector view
        # does not restore them from the error details' strings, which the
        # mutation views do.
        assert set(sent) == {"detail", "schema"}
        assert set(sent["schema"]) == set(_ASK_SCHEMA)
        documented = _documented(schema, "asking", "422")
        jsonschema.validate(sent, documented)
        component = schema["components"]["schemas"]["ServiceError"]
        assert component["properties"]["schema"]["type"] == "object"
        assert component["required"] == ["detail"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"detail": "x", "schema": "a string"}, documented)
