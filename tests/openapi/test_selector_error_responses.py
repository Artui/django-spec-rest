from __future__ import annotations

import json
from typing import Any

import django_filters
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
from django_spec_rest.openapi import SERVICE_ERROR_METADATA_KEY, enable_openapi
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


class _PostFilter(django_filters.FilterSet):
    kind = django_filters.ChoiceFilter(field_name="body", choices=[("a", "A"), ("b", "B")])

    class Meta:
        model = Post
        fields: list[str] = []


def _every_post() -> Any:
    return Post.objects.order_by("id")


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
# The specs whose selector raises, which declare the 422 they are answered with.
_DECLARED = {SERVICE_ERROR_METADATA_KEY: True}
_RAISING = ("unprocessable", "asking", "captured")

# Each route: its view, its spec, and the URL it is mounted at.
_SPECS: dict[str, tuple[type, SelectorSpec]] = {
    "read": (SelectorListView, _spec(_posts, reads=_PUBLISHED)),
    "unprocessable": (SelectorListView, _spec(_unprocessable, metadata=_DECLARED)),
    "asking": (SelectorListView, _spec(_asking, metadata=_DECLARED)),
    "filtered": (SelectorListView, _spec(_every_post, filter_set=_PostFilter)),
    "no-reads": (SelectorListView, _spec(_posts)),
    "captured": (
        SelectorRetrieveView,
        _spec(_unprocessable, kind=SelectorKind.RETRIEVE, reads=_ROWS, metadata=_DECLARED),
    ),
}

urlpatterns = [
    path(
        f"{key}/<int:pk>/" if key == "captured" else f"{key}/",
        type("_View", (view,), {"spec": spec, "queryset": Post.objects.all()}).as_view(),
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


def _get(key: str, query: str = "", *, pk: str = "1") -> tuple[int, Any]:
    view = urlpatterns[list(_SPECS).index(key)].callback
    kwargs = {"pk": pk} if key == "captured" else {}
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

    def test_a_filter_is_refused_under_its_name(self, schema: dict[str, Any]) -> None:
        status, sent = _get("filtered", "?kind=zzz")
        assert status == 400
        assert list(sent) == ["kind"]
        jsonschema.validate(sent, _documented(schema, "filtered", "400"))

    def test_a_route_capture_is_refused_under_its_name(self, schema: dict[str, Any]) -> None:
        # The route's converter would match only digits.
        status, sent = _get("captured", pk="abc")
        assert status == 400
        assert list(sent) == ["pk"]
        jsonschema.validate(sent, _documented(schema, "captured", "400"))

    def test_a_selector_with_no_parameter_documents_no_400_for_a_key_it_drops(
        self, schema: dict[str, Any]
    ) -> None:
        assert _get("no-reads", "?nope=1")[0] == 200
        assert "400" not in _responses(schema, "no-reads")

    def test_the_success_response_is_kept(self, schema: dict[str, Any]) -> None:
        documented = _documented(schema, "read", "200")
        assert documented["type"] == "array"
        assert _get("read", "?published=true") == (200, [])


@pytest.mark.django_db
class TestA422IsASelectorRefusal:
    @pytest.mark.parametrize("key", list(_SPECS))
    def test_it_is_documented_where_the_spec_declares_it(
        self, schema: dict[str, Any], key: str
    ) -> None:
        # Whatever the selector reads: a read, a filter, a capture or none.
        assert ("422" in _responses(schema, key)) is (key in _RAISING)

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
        assert sent == {"detail": "Say which.", "schema": _ASK_SCHEMA}
        documented = _documented(schema, "asking", "422")
        jsonschema.validate(sent, documented)
        component = schema["components"]["schemas"]["ServiceError"]
        assert component["properties"]["schema"]["type"] == "object"
        assert component["required"] == ["detail"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"detail": "x", "schema": "a string"}, documented)
