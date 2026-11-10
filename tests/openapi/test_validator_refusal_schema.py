from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import jsonschema
import pytest
from django.urls import path
from django_service_specs import (
    DataclassValidator,
    Parameter,
    Parameters,
    ServiceError,
    ServiceSpec,
    ServiceValidationError,
    Unrestricted,
    Validator,
)
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from drf_spectacular.generators import SchemaGenerator
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView
from django_spec_rest.openapi import SERVICE_ERROR_METADATA_KEY, enable_openapi
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer


class _Address(serializers.Serializer):
    street = serializers.IntegerField()


class _Person(serializers.Serializer):
    name = serializers.CharField(max_length=3)
    address = _Address()
    tags = serializers.ListField(child=serializers.IntegerField())

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["name"] == "bad":
            raise serializers.ValidationError("The whole is refused.")
        return attrs


@dataclass
class _Row:
    name: str
    count: int


class _Refusing(Validator):
    """A Validator that is no serializer and refuses with the kernel's ``InvalidArguments``."""

    def parameters(self) -> Parameters:
        return Parameters.of(Parameter("name", "string", required=True))

    def validate(self, arguments: Any, context: Any) -> dict[str, Any]:
        raise InvalidArguments({"name": ["Not that one."]})


def _store(*, data: Any = None, **_: Any) -> None: ...


def _unprocessable(*, data: Any = None, **_: Any) -> None:
    raise ServiceError("Could not.")


def _refusing(detail: Any) -> Any:
    def service(*, data: Any = None, **_: Any) -> None:
        raise ServiceValidationError(detail)

    return service


def _spec(validator: Validator | None, **fields: Any) -> ServiceSpec:
    return ServiceSpec(
        **{
            "service": _store,
            "permissions": (Unrestricted(),),
            "validator": validator,
            "presenter": SerializerPresenter(AuthorSerializer),
            **fields,
        }
    )


# The specs whose service raises a plain ``ServiceError`` declare its 422.
_DECLARED = {SERVICE_ERROR_METADATA_KEY: True}

_SPECS: dict[str, ServiceSpec] = {
    "serializer": _spec(SerializerValidator(_Person)),
    "serializer-many": _spec(SerializerValidator(_Person), many=True),
    "dataclass": _spec(DataclassValidator(_Row)),
    "dataclass-many": _spec(DataclassValidator(_Row), many=True),
    "custom": _spec(_Refusing()),
    "unprocessable": _spec(
        SerializerValidator(_Person), service=_unprocessable, metadata=_DECLARED
    ),
    "unprocessable-bare": _spec(None, service=_unprocessable, metadata=_DECLARED),
    # A service's own ``ServiceValidationError`` is answered as DRF answers
    # ``ValidationError(detail)``: a sentence or a list of them is a bare list,
    # a mapping's string is a string leaf.
    "service-sentence": _spec(SerializerValidator(_Person), service=_refusing("Bad.")),
    "service-list": _spec(SerializerValidator(_Person), service=_refusing(["Bad."])),
    "service-mapping": _spec(SerializerValidator(_Person), service=_refusing({"name": "Bad."})),
}

_VALID = {"name": "ab", "address": {"street": 1}, "tags": [1]}

# A body each spec refuses, covering the shapes DRF's errors take: a message
# list under a field, a nested object, an object keyed by a row's index, and the
# non-field list.
_REFUSED: dict[str, Any] = {
    "serializer": {},
    "serializer-nested": {"name": "ab", "address": {"street": "x"}, "tags": [1, "y"]},
    "serializer-non-field": {"name": "bad", "address": {"street": 1}, "tags": []},
    "serializer-many": [_VALID, {"name": "ab", "address": {"street": "x"}, "tags": []}, {}],
    "dataclass": {"name": 1},
    "dataclass-many": [{"name": "a", "count": 1}, {"name": 2}],
    "custom": {"name": "a"},
}

urlpatterns = [
    path(
        f"{key}/",
        type(
            "_View",
            (ServiceCreateView,),
            {"queryset": Author.objects.all(), "spec": spec},
        ).as_view(),
    )
    for key, spec in _SPECS.items()
]


@pytest.fixture(scope="module", autouse=True)
def _enable_openapi() -> None:
    enable_openapi()


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)


def _responses(schema: dict[str, Any], key: str) -> dict[str, Any]:
    return schema["paths"][f"/{key}/"]["post"]["responses"]


def _documented(schema: dict[str, Any], key: str, status: str) -> dict[str, Any]:
    """The schema ``key``'s operation documents for ``status``, with the document's components."""
    body = _responses(schema, key)[status]["content"]["application/json"]["schema"]
    return {**body, "components": schema["components"]}


def _post(key: str, body: Any) -> tuple[int, Any]:
    view = urlpatterns[list(_SPECS).index(key)].callback
    response = view(APIRequestFactory().post("/", body, format="json"))
    response.render()
    return response.status_code, json.loads(response.content)


@pytest.mark.django_db
class TestARefusedCallIsA400:
    @pytest.mark.parametrize(
        ("key", "body"),
        [
            ("serializer", _REFUSED["serializer"]),
            ("serializer", _REFUSED["serializer-nested"]),
            ("serializer", _REFUSED["serializer-non-field"]),
            ("serializer-many", _REFUSED["serializer-many"]),
            ("dataclass", _REFUSED["dataclass"]),
            ("dataclass-many", _REFUSED["dataclass-many"]),
            ("custom", _REFUSED["custom"]),
        ],
    )
    def test_the_documented_400_describes_the_body_the_edge_sends(
        self, schema: dict[str, Any], key: str, body: Any
    ) -> None:
        status, sent = _post(key, body)
        assert status == 400
        jsonschema.validate(sent, _documented(schema, key, "400"))

    def test_a_body_that_is_no_object_is_a_detail_the_400_also_describes(
        self, schema: dict[str, Any]
    ) -> None:
        status, sent = _post("serializer", [1])
        assert status == 400
        assert set(sent) == {"detail"}
        jsonschema.validate(sent, _documented(schema, "serializer", "400"))

    @pytest.mark.parametrize(
        ("key", "wire"),
        [
            ("service-sentence", ["Bad."]),
            ("service-list", ["Bad."]),
            ("service-mapping", {"name": "Bad."}),
        ],
    )
    def test_a_service_s_validation_error_is_documented_in_the_shape_it_is_sent(
        self, schema: dict[str, Any], key: str, wire: Any
    ) -> None:
        status, sent = _post(key, _VALID)
        assert (status, sent) == (400, wire)
        jsonschema.validate(sent, _documented(schema, key, "400"))

    def test_the_400_refuses_a_body_the_edge_never_sends(self, schema: dict[str, Any]) -> None:
        documented = _documented(schema, "serializer", "400")
        for never in ({"name": 1}, {"name": [1]}, {"name": {"a": 1}}, ["x", 1], "x", [[]]):
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(never, documented)

    @pytest.mark.parametrize("key", ["serializer", "serializer-many", "dataclass", "custom"])
    def test_it_is_documented_wherever_there_is_a_validator(
        self, schema: dict[str, Any], key: str
    ) -> None:
        assert "400" in _responses(schema, key)

    def test_it_is_one_reusable_component(self, schema: dict[str, Any]) -> None:
        refs = {
            json.dumps(_responses(schema, key)["400"], sort_keys=True)
            for key in ("serializer", "serializer-many", "dataclass", "dataclass-many", "custom")
        }
        assert len(refs) == 1
        assert "ValidationErrors" in schema["components"]["schemas"]

    def test_a_spec_with_no_validator_documents_no_400(self, schema: dict[str, Any]) -> None:
        assert "400" not in _responses(schema, "unprocessable-bare")


@pytest.mark.django_db
class TestA422IsAServiceRefusal:
    def test_a_validator_s_refusal_is_not_a_422(self) -> None:
        for key, body in (
            ("serializer", {}),
            ("dataclass", {"name": 1}),
            ("custom", {"name": "a"}),
        ):
            assert _post(key, body)[0] != 422

    @pytest.mark.parametrize("key", ["unprocessable", "unprocessable-bare"])
    def test_the_documented_422_describes_the_body_the_edge_sends(
        self, schema: dict[str, Any], key: str
    ) -> None:
        status, sent = _post(key, _VALID)
        assert (status, sent) == (422, {"detail": "Could not."})
        jsonschema.validate(sent, _documented(schema, key, "422"))

    def test_it_is_documented_where_declared_whether_or_not_the_spec_has_a_validator(
        self, schema: dict[str, Any]
    ) -> None:
        for key, spec in _SPECS.items():
            assert ("422" in _responses(schema, key)) is (spec.metadata is not None)
