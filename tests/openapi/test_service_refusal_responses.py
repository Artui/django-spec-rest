"""The serializers a project declares a service's refusals with, against what the edge sends.

Which refusals a service raises is the project's to declare, so the package
exports a schema-only serializer per body ``map_service_error`` answers a
``ServiceError`` with. Each view here declares one through
``@extend_schema(responses=...)``, its service raises the refusal, and the body
the edge sends is validated against the response the operation documents: the
body is the producer's, never typed here.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

import jsonschema
import pytest
from django.urls import path
from django_service_specs import (
    ActionUnavailable,
    AdditionalInputRequired,
    DataclassValidator,
    ServiceConflict,
    ServiceError,
    ServiceNotFound,
    ServiceSpec,
    ServiceValidationError,
    Unrestricted,
)
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import extend_schema
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView
from django_spec_rest.openapi import (
    ActionUnavailableSerializer,
    ServiceConflictSerializer,
    ServiceErrorSerializer,
    ServiceNotFoundSerializer,
    ServiceValidationErrorSerializer,
    enable_openapi,
)
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.openapi.test_validator_refusal_schema import _REFUSED, _Person, _Refusing, _Row

# ``extend_schema`` subclasses the schema the class has when it is decorated,
# so the package's schema is set first, as a project's ``AppConfig.ready()``
# sets it before its URLconf imports its views.
enable_openapi()

_ASK = {"type": "object", "properties": {"due": {"type": "string", "default": False}}}

# key: (the refusal the service raises, the status it is answered with, the
# serializer the view declares for that status)
_CASES: dict[str, tuple[ServiceError, int, Any]] = {
    "service-error": (ServiceError("Could not."), 422, ServiceErrorSerializer),
    "service-error-default": (ServiceError(), 422, ServiceErrorSerializer),
    "additional-input": (
        AdditionalInputRequired("Need a date.", schema=_ASK),
        422,
        ServiceErrorSerializer,
    ),
    "additional-input-bare": (AdditionalInputRequired("Need a date."), 422, ServiceErrorSerializer),
    "not-found": (ServiceNotFound("No such task."), 404, ServiceNotFoundSerializer),
    "conflict": (ServiceConflict("Taken."), 409, ServiceConflictSerializer),
    "action-unavailable": (
        ActionUnavailable("Closed.", code="closed"),
        409,
        ActionUnavailableSerializer,
    ),
    # A service raising ``ServiceConflict`` may raise its ``ActionUnavailable``.
    "action-unavailable-as-conflict": (
        ActionUnavailable("Closed.", code="closed"),
        409,
        ServiceConflictSerializer,
    ),
    # Every shape DRF's ``ValidationError(detail)`` sends.
    "validation-sentence": (ServiceValidationError("Bad."), 400, ServiceValidationErrorSerializer),
    "validation-list": (
        ServiceValidationError(["Bad.", "Worse."]),
        400,
        ServiceValidationErrorSerializer,
    ),
    "validation-mapping": (
        ServiceValidationError({"name": "Bad."}),
        400,
        ServiceValidationErrorSerializer,
    ),
    "validation-mapping-of-lists": (
        ServiceValidationError({"name": ["Bad."], "non_field_errors": ["No."]}),
        400,
        ServiceValidationErrorSerializer,
    ),
    "validation-list-of-mappings": (
        ServiceValidationError([{"name": "Bad."}, {"age": ["Too old."]}]),
        400,
        ServiceValidationErrorSerializer,
    ),
    "validation-deep": (
        ServiceValidationError({"rows": [{"tags": [["x"], {"y": "z"}]}], "owner": {"id": "No."}}),
        400,
        ServiceValidationErrorSerializer,
    ),
    "validation-list-of-lists": (
        ServiceValidationError([["a"], []]),
        400,
        ServiceValidationErrorSerializer,
    ),
    "validation-empty-mapping": (
        ServiceValidationError({}),
        400,
        ServiceValidationErrorSerializer,
    ),
}


def _raising(exc: ServiceError) -> Any:
    def service(**_: Any) -> None:
        raise exc

    return service


def _declaring(spec: ServiceSpec, responses: dict[Any, Any]) -> type:
    return extend_schema(responses=responses)(
        type("_View", (ServiceCreateView,), {"spec": spec, "permission_classes": []})
    )


_SPECS = {
    key: ServiceSpec(service=_raising(exc), permissions=(Unrestricted(),))
    for key, (exc, _, _) in _CASES.items()
}

# Each validator's refusal under the spec's own 400, and under a declared
# ``ServiceValidationErrorSerializer`` that replaces it at that status.
_VALIDATORS = {
    "serializer": SerializerValidator(_Person),
    "serializer-many": SerializerValidator(_Person),
    "dataclass": DataclassValidator(_Row),
    "dataclass-many": DataclassValidator(_Row),
    "custom": _Refusing(),
}


def _validated(key: str) -> ServiceSpec:
    return ServiceSpec(
        service=lambda **_: None,
        permissions=(Unrestricted(),),
        validator=_VALIDATORS[key],
        many=key.endswith("-many"),
    )


urlpatterns = [
    *(
        path(f"{key}/", _declaring(_SPECS[key], {status: serializer}).as_view())
        for key, (_, status, serializer) in _CASES.items()
    ),
    *(
        path(
            f"declared-{key}/",
            _declaring(_validated(key), {400: ServiceValidationErrorSerializer}).as_view(),
        )
        for key in _VALIDATORS
    ),
]


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)


def _responses(schema: dict[str, Any], route: str) -> dict[str, Any]:
    return schema["paths"][f"/{route}/"]["post"]["responses"]


def _documented(schema: dict[str, Any], route: str, status: int) -> dict[str, Any]:
    body = _responses(schema, route)[str(status)]["content"]["application/json"]["schema"]
    return {**body, "components": schema["components"]}


def _post(route: str, body: Any = None) -> tuple[int, Any]:
    view = next(p.callback for p in urlpatterns if str(p.pattern) == f"{route}/")
    response = view(APIRequestFactory().post("/", body if body is not None else {}, format="json"))
    response.render()
    return response.status_code, json.loads(response.content)


def _subclasses(cls: type) -> set[type]:
    found = {cls}
    for sub in cls.__subclasses__():
        found |= _subclasses(sub)
    return found


def test_every_service_error_the_kernel_ships_has_a_case() -> None:
    shipped = {
        cls
        for cls in _subclasses(ServiceError)
        if cls.__module__.startswith("django_service_specs")
    }
    assert shipped == {type(exc) for exc, _, _ in _CASES.values()}


@pytest.mark.parametrize(
    ("serializer", "component"),
    [
        (ServiceErrorSerializer, "ServiceError"),
        (ServiceNotFoundSerializer, "ServiceNotFound"),
        (ServiceConflictSerializer, "ServiceConflict"),
        (ActionUnavailableSerializer, "ActionUnavailable"),
        (ServiceValidationErrorSerializer, "ServiceValidationError"),
    ],
)
def test_a_declared_serializer_is_documented_as_its_component(
    schema: dict[str, Any], serializer: Any, component: str
) -> None:
    key, (_, status, _) = next((key, case) for key, case in _CASES.items() if case[2] is serializer)
    assert _responses(schema, key)[str(status)]["content"]["application/json"]["schema"] == {
        "$ref": f"#/components/schemas/{component}"
    }
    assert schema["components"]["schemas"][component]["description"] == inspect.cleandoc(
        serializer.__doc__
    )


@pytest.mark.django_db
@pytest.mark.parametrize("key", list(_CASES))
def test_each_service_error_the_edge_sends_is_the_documented_body(
    schema: dict[str, Any], key: str
) -> None:
    _, status, _ = _CASES[key]
    sent_status, sent = _post(key)
    assert sent_status == status
    jsonschema.validate(sent, _documented(schema, key, status))


@pytest.mark.django_db
def test_the_validation_cases_reach_the_wire_as_drf_sends_them() -> None:
    # The wire bodies themselves, so a case list that lost its depth fails here.
    assert _post("validation-sentence") == (400, ["Bad."])
    assert _post("validation-list-of-mappings") == (400, [{"name": "Bad."}, {"age": ["Too old."]}])
    assert _post("validation-deep") == (
        400,
        {"rows": [{"tags": [["x"], {"y": "z"}]}], "owner": {"id": "No."}},
    )


@pytest.mark.parametrize("body", ["Bad.", 1, None, [1], {"name": 1}, [{"name": [None]}]])
def test_the_service_validation_error_admits_nothing_drf_never_sends(
    schema: dict[str, Any], body: Any
) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(body, _documented(schema, "validation-sentence", 400))


def test_an_action_unavailable_requires_its_code(schema: dict[str, Any]) -> None:
    documented = _documented(schema, "action-unavailable", 409)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"detail": "Taken."}, documented)
    jsonschema.validate({"detail": "Taken."}, _documented(schema, "conflict", 409))


@pytest.mark.django_db
class TestEveryBodyTheValidatorS400SendsIsAdmitted:
    """Declared ``ServiceValidationErrorSerializer`` replaces a Validator's 400, keeping bodies."""

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
            # A body that is no object, answered with a ``detail``.
            ("serializer", [1]),
        ],
    )
    def test_every_body_the_validator_s_400_sends_is_admitted(
        self, schema: dict[str, Any], key: str, body: Any
    ) -> None:
        route = f"declared-{key}"
        assert _responses(schema, route)["400"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ServiceValidationError"
        }
        status, sent = _post(route, body)
        assert status == 400
        jsonschema.validate(sent, _documented(schema, route, 400))
