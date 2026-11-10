"""``requestBody.required`` where the body is a whole schema, which drf-spectacular marks optional.

The wire is the check: where every spec the route may run takes a body with a
required field, an empty body is refused, and the document says so. Where one may
run with no body, or with none of its fields required, an empty body gets through,
and the document leaves ``required`` out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from django.urls import path
from django_service_specs import (
    DataclassValidator,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import OpenApiRequest, extend_schema, extend_schema_view
from rest_framework import serializers
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import ServiceCreateView, ServiceViewSet, service_action
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.types.discriminated_action import DiscriminatedAction
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db

_OPEN = (Unrestricted(),)
_BY_PK = Parameters.of(Parameter("pk", "integer", required=True))


class AIn(serializers.Serializer):
    alpha = serializers.CharField()


class BIn(serializers.Serializer):
    beta = serializers.IntegerField()


class OptionalIn(serializers.Serializer):
    gamma = serializers.CharField(required=False)


class TenantIn(serializers.Serializer):
    tenant = serializers.CharField()


@dataclass
class Row:
    sku: str


@dataclass
class OptionalRow:
    note: str = field(default="")


def _service(**_: Any) -> None: ...


def _spec(validator: Any = None, **fields: Any) -> ServiceSpec:
    return ServiceSpec(
        service=_service, permissions=_OPEN, validator=validator, allow_none=True, **fields
    )


def _target() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
        reads=_BY_PK,
    )


def _choosing(chosen: str, **variants: ServiceSpec) -> DiscriminatedAction:
    return DiscriminatedAction(lambda: chosen, variants)


def _viewset(name: str, key: str, entry: Any) -> type:
    return type(
        name, (ServiceViewSet,), {"queryset": Author.objects.all(), "action_specs": {key: entry}}
    )


EVERY = _viewset(
    "Every",
    "create",
    _choosing("a", a=_spec(SerializerValidator(AIn)), b=_spec(SerializerValidator(BIn))),
)
NO_BODY = _viewset("NoBody", "create", _choosing("c", a=_spec(SerializerValidator(AIn)), c=_spec()))
ALL_OPTIONAL = _viewset(
    "AllOptional",
    "create",
    _choosing("o", a=_spec(SerializerValidator(AIn)), o=_spec(SerializerValidator(OptionalIn))),
)
OTHER_VALIDATOR = _viewset(
    "OtherValidator",
    "create",
    _choosing("r", a=_spec(SerializerValidator(AIn)), r=_spec(DataclassValidator(Row))),
)
ROWS = _viewset(
    "Rows",
    "create",
    _choosing(
        "rows", rows=_spec(SerializerValidator(AIn), many=True), a=_spec(SerializerValidator(BIn))
    ),
)
CAPTURED = _viewset(
    "Captured",
    "create",
    _choosing("t", a=_spec(SerializerValidator(AIn)), t=_spec(SerializerValidator(TenantIn))),
)
ROUTED_PATCH = _viewset(
    "RoutedPatch",
    "partial_update",
    _choosing(
        "a",
        a=_spec(SerializerValidator(AIn), instance_selector_spec=_target()),
        b=_spec(SerializerValidator(BIn), instance_selector_spec=_target()),
    ),
)
DESTROYED = _viewset(
    "Destroyed",
    "destroy",
    _choosing("a", a=_spec(SerializerValidator(AIn), instance_selector_spec=_target())),
)
DESTROYED_HALF = _viewset(
    "DestroyedHalf",
    "destroy",
    _choosing(
        "p",
        a=_spec(SerializerValidator(AIn), instance_selector_spec=_target()),
        p=_spec(instance_selector_spec=_target()),
    ),
)


class Decorated(GenericViewSet):
    queryset = Author.objects.all()

    @service_action(
        _choosing(
            "a",
            a=_spec(SerializerValidator(AIn), instance_selector_spec=_target()),
            b=_spec(SerializerValidator(BIn), instance_selector_spec=_target()),
        ),
        detail=True,
        methods=["patch"],
    )
    def rename(self, request: Any, pk: int) -> Any: ...


@extend_schema_view(
    create=extend_schema(request=OpenApiRequest({"type": "object", "title": "Declared"}))
)
class DeclaredRequest(ServiceViewSet):
    """A request a project declares is theirs: the variants' bodies are not read."""

    queryset = Author.objects.all()
    action_specs = {"create": _choosing("a", a=_spec(SerializerValidator(AIn)))}


class PlainOther(ServiceCreateView):
    spec = _spec(DataclassValidator(Row))


class PlainOptional(ServiceCreateView):
    spec = _spec(DataclassValidator(OptionalRow))


class PlainMany(ServiceCreateView):
    spec = _spec(DataclassValidator(Row), many=True)


class PlainSerializer(ServiceCreateView):
    spec = _spec(SerializerValidator(AIn))


_CREATE = {"post": "create"}
urlpatterns = [
    path("every/", EVERY.as_view(_CREATE)),
    path("no-body/", NO_BODY.as_view(_CREATE)),
    path("all-optional/", ALL_OPTIONAL.as_view(_CREATE)),
    path("other-validator/", OTHER_VALIDATOR.as_view(_CREATE)),
    path("rows/", ROWS.as_view(_CREATE)),
    path("captured/<str:tenant>/", CAPTURED.as_view(_CREATE)),
    path("routed-patch/<int:pk>/", ROUTED_PATCH.as_view({"patch": "partial_update"})),
    path("destroyed/<int:pk>/", DESTROYED.as_view({"delete": "destroy"})),
    path("destroyed-half/<int:pk>/", DESTROYED_HALF.as_view({"delete": "destroy"})),
    path("decorated/<int:pk>/rename/", Decorated.as_view({"patch": "rename"})),
    path("declared/", DeclaredRequest.as_view(_CREATE)),
    path("plain-other/", PlainOther.as_view()),
    path("plain-optional/", PlainOptional.as_view()),
    path("plain-many/", PlainMany.as_view()),
    path("plain-serializer/", PlainSerializer.as_view()),
]


@pytest.fixture(scope="module", autouse=True)
def _enable_openapi() -> None:
    enable_openapi()


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)


def _request_body(schema: dict[str, Any], route: str, method: str = "post") -> dict[str, Any]:
    return schema["paths"][route][method]["requestBody"]


def _empty_post(view: Any, **captures: Any) -> int:
    return view(APIRequestFactory().post("/", {}, format="json"), **captures).status_code


class TestEveryVariantDemandsABody:
    @pytest.mark.parametrize(
        ("route", "view"),
        [
            ("/every/", EVERY.as_view(_CREATE)),
            ("/other-validator/", OTHER_VALIDATOR.as_view(_CREATE)),
            ("/rows/", ROWS.as_view(_CREATE)),
        ],
        ids=["serializers", "a-raw-schema", "a-many-variant"],
    )
    def test_it_is_required_as_the_wire_refuses_an_empty_body(
        self, schema: dict[str, Any], route: str, view: Any
    ) -> None:
        assert _empty_post(view) == 400
        assert _request_body(schema, route)["required"] is True

    def test_a_decorated_patch_validated_whole_is_required(self, schema: dict[str, Any]) -> None:
        assert _request_body(schema, "/decorated/{id}/rename/", "patch")["required"] is True

    def test_a_delete_taking_a_required_body_is_required(self, schema: dict[str, Any]) -> None:
        assert _request_body(schema, "/destroyed/{id}/", "delete")["required"] is True


class TestAVariantTakingNoBody:
    @pytest.mark.parametrize(
        ("route", "view", "captures"),
        [
            ("/no-body/", NO_BODY.as_view(_CREATE), {}),
            ("/all-optional/", ALL_OPTIONAL.as_view(_CREATE), {}),
            ("/captured/{tenant}/", CAPTURED.as_view(_CREATE), {"tenant": "t"}),
        ],
        ids=["no-validator", "no-required-field", "its-field-a-route-capture"],
    )
    def test_it_stays_absent_as_the_wire_lets_an_empty_body_through(
        self, schema: dict[str, Any], route: str, view: Any, captures: dict[str, str]
    ) -> None:
        assert _empty_post(view, **captures) == 204
        assert "required" not in _request_body(schema, route)

    def test_a_routed_patch_asks_a_partial_call_of_every_variant(
        self, schema: dict[str, Any]
    ) -> None:
        assert "required" not in _request_body(schema, "/routed-patch/{id}/", "patch")

    def test_a_delete_with_a_variant_taking_no_body(self, schema: dict[str, Any]) -> None:
        assert "required" not in _request_body(schema, "/destroyed-half/{id}/", "delete")


class TestWhatTheVariantsDoNotAnswer:
    def test_a_request_a_project_declares_is_theirs(self, schema: dict[str, Any]) -> None:
        body = _request_body(schema, "/declared/")
        assert body["content"]["application/json"]["schema"]["title"] == "Declared"
        assert "required" not in body


def _named_alike(entry: Any, route: str) -> Any:
    # A fixed route, not ``id(entry)``: the generator orders operations by path, and
    # the first of one name is the one that holds the component, so an address-
    # dependent route flipped which was "held" with the heap's layout.
    return path(f"{route}/", _viewset("Alike", "create", entry).as_view(_CREATE))


class TestAnAnyOfGivenInline:
    """A second operation of one name documents its own ``anyOf``, and states ``required`` of it."""

    def _inline_body(self, entry: Any) -> dict[str, Any]:
        held = _named_alike(_choosing("a", a=_spec(SerializerValidator(AIn))), "held")
        inline = _named_alike(entry, "inline")
        paths = SchemaGenerator(patterns=[held, inline]).get_schema(request=None, public=True)
        bodies = [operation["post"]["requestBody"] for operation in paths["paths"].values()]
        (body,) = [b for b in bodies if "anyOf" in b["content"]["application/json"]["schema"]]
        return body

    def test_every_variant_demanding_a_body_is_required(self) -> None:
        body = self._inline_body(_choosing("b", b=_spec(SerializerValidator(BIn))))
        assert body["required"] is True

    def test_a_variant_taking_none_leaves_it_absent(self) -> None:
        body = self._inline_body(_choosing("b", b=_spec(SerializerValidator(BIn)), c=_spec()))
        assert "required" not in body


class TestAPlainSpecOverARawSchema:
    @pytest.mark.parametrize(
        ("route", "view"),
        [("/plain-other/", PlainOther.as_view()), ("/plain-many/", PlainMany.as_view())],
        ids=["one-row", "many"],
    )
    def test_it_is_required_as_the_wire_refuses_an_empty_body(
        self, schema: dict[str, Any], route: str, view: Any
    ) -> None:
        assert _empty_post(view) == 400
        assert _request_body(schema, route)["required"] is True

    def test_no_required_field_leaves_it_absent(self, schema: dict[str, Any]) -> None:
        assert _empty_post(PlainOptional.as_view()) == 204
        assert "required" not in _request_body(schema, "/plain-optional/")

    def test_a_serializer_keeps_drf_spectacular_s_reading(self, schema: dict[str, Any]) -> None:
        assert _request_body(schema, "/plain-serializer/")["required"] is True

    def test_what_it_documents_is_a_plain_mapping_the_yaml_renderer_takes(
        self, schema: dict[str, Any]
    ) -> None:
        for route in ("/plain-other/", "/plain-many/", "/every/"):
            body = _request_body(schema, route)["content"]["application/json"]["schema"]
            assert type(body) is dict
        members = schema["components"]["schemas"]["OtherValidator_create_Request"]["anyOf"]
        assert all(type(member) is dict for member in members)
