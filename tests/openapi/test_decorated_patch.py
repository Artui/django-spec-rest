"""A ``@service_action`` ``PATCH`` is validated whole, so it is documented whole.

Only an update route asks the kernel for a partial call; a decorated action
dispatches the spec as declared, so a spec declaring ``partial`` is the way to a
partial one. Each test reads the required list off the document and off a real
request, since the two must state one thing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pytest
from django_service_specs import (
    DataclassValidator,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
    ValidationContext,
    Validator,
)
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from drf_spectacular.generators import SchemaGenerator
from rest_framework import serializers
from rest_framework.routers import DefaultRouter
from rest_framework.test import APIClient
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import ServiceViewSet, service_action
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.types.discriminated_action import DiscriminatedAction
from tests.testapp.models import Author

_OPEN = (Unrestricted(),)
_BY_PK = Parameters.of(Parameter("pk", "integer", required=True))


class TitleIn(serializers.Serializer):
    title = serializers.CharField()
    note = serializers.CharField(required=False)


class SlugIn(serializers.Serializer):
    slug = serializers.CharField()


@dataclass
class Colour:
    colour: str


class _Declared(Validator):
    """A Validator that could take a partial call, and is only asked for one by a partial spec."""

    def parameters(self) -> Parameters:
        return Parameters.of(Parameter("shade", "string", required=True))

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        if not context.partial and "shade" not in arguments:
            raise InvalidArguments({"shade": ["This field is required."]})
        return dict(arguments)


def _service(**_: Any) -> None: ...


def _target() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
        reads=_BY_PK,
    )


def _on_a_row(validator: Any, **fields: Any) -> ServiceSpec:
    return ServiceSpec(
        service=_service,
        permissions=_OPEN,
        validator=validator,
        allow_none=True,
        instance_selector_spec=_target(),
        **fields,
    )


class Decorated(GenericViewSet):
    queryset = Author.objects.all()

    @service_action(
        _on_a_row(SerializerValidator(TitleIn)), detail=True, methods=["patch"], url_path="whole"
    )
    def whole(self, request: Any, pk: int) -> Any: ...

    @service_action(
        _on_a_row(SerializerValidator(TitleIn), partial=True),
        detail=True,
        methods=["patch"],
        url_path="declared-partial",
    )
    def declared_partial(self, request: Any, pk: int) -> Any: ...

    @service_action(
        _on_a_row(_Declared()), detail=True, methods=["patch"], url_path="other-validator"
    )
    def other_validator(self, request: Any, pk: int) -> Any: ...

    @service_action(
        _on_a_row(DataclassValidator(Colour)), detail=True, methods=["patch"], url_path="dataclass"
    )
    def dataclass_body(self, request: Any, pk: int) -> Any: ...

    @service_action(
        DiscriminatedAction(
            lambda: "title",
            {
                "title": _on_a_row(SerializerValidator(TitleIn)),
                "slug": _on_a_row(SerializerValidator(SlugIn)),
            },
        ),
        detail=True,
        methods=["patch"],
        url_path="variants",
    )
    def variants(self, request: Any, pk: int) -> Any: ...

    @service_action(
        DiscriminatedAction(
            lambda: "title",
            {
                "title": _on_a_row(SerializerValidator(TitleIn), partial=True),
                "shade": _on_a_row(_Declared()),
            },
        ),
        detail=True,
        methods=["patch"],
        url_path="partial-variant",
    )
    def partial_variant(self, request: Any, pk: int) -> Any: ...

    @service_action(
        DiscriminatedAction(lambda: "title", {"title": _on_a_row(SerializerValidator(TitleIn))}),
        detail=True,
        methods=["put", "patch"],
        url_path="both-methods",
    )
    def both_methods(self, request: Any, pk: int) -> Any: ...


class Routed(ServiceViewSet):
    """A router's ``partial_update``, the route that does ask for a partial call."""

    queryset = Author.objects.all()
    action_specs = {"partial_update": _on_a_row(SerializerValidator(TitleIn))}


_router = DefaultRouter()
_router.register("decorated", Decorated, basename="decorated")
_router.register("routed", Routed, basename="routed")

urlpatterns = _router.urls


@pytest.fixture(scope="module", autouse=True)
def _enable_openapi() -> None:
    enable_openapi()


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)


def _request_body(schema: dict[str, Any], route: str, method: str = "patch") -> dict[str, Any]:
    return schema["paths"][route][method]["requestBody"]


def _body(schema: dict[str, Any], route: str, method: str = "patch") -> dict[str, Any]:
    return _request_body(schema, route, method)["content"]["application/json"]["schema"]


def _resolved(schema: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    if "$ref" not in reference:
        return reference
    return schema["components"]["schemas"][reference["$ref"].rsplit("/", 1)[1]]


@pytest.fixture
def author() -> Author:
    return Author.objects.create(name="a")


def _patch(route: str, pk: int, body: dict[str, Any]) -> Any:
    return APIClient().patch(f"/{route}/{pk}/{{}}/", body, format="json")


@pytest.mark.urls(__name__)
@pytest.mark.django_db
class TestAPlainSpec:
    def test_a_serializer_is_documented_whole_as_the_wire_demands(
        self, schema: dict[str, Any], author: Author
    ) -> None:
        documented = _body(schema, "/decorated/{id}/whole/")
        assert documented == {"$ref": "#/components/schemas/TitleIn"}
        response = APIClient().patch(f"/decorated/{author.pk}/whole/", {}, format="json")
        assert response.status_code == 400
        assert sorted(response.data) == _resolved(schema, documented)["required"] == ["title"]

    def test_another_validator_is_documented_whole_as_the_wire_demands(
        self, schema: dict[str, Any], author: Author
    ) -> None:
        documented = _body(schema, "/decorated/{id}/other-validator/")
        response = APIClient().patch(f"/decorated/{author.pk}/other-validator/", {}, format="json")
        assert response.status_code == 400
        assert sorted(response.data) == documented["required"] == ["shade"]

    def test_a_dataclass_stays_whole(self, schema: dict[str, Any], author: Author) -> None:
        documented = _body(schema, "/decorated/{id}/dataclass/")
        response = APIClient().patch(f"/decorated/{author.pk}/dataclass/", {}, format="json")
        assert response.status_code == 400
        assert sorted(response.data) == documented["required"] == ["colour"]

    def test_a_spec_declaring_partial_is_the_way_to_a_partial_call(
        self, schema: dict[str, Any], author: Author
    ) -> None:
        documented = _body(schema, "/decorated/{id}/declared-partial/")
        assert documented == {"$ref": "#/components/schemas/PatchedTitleIn"}
        assert "required" not in _resolved(schema, documented)
        response = APIClient().patch(f"/decorated/{author.pk}/declared-partial/", {}, format="json")
        assert response.status_code == 204

    def test_the_route_that_asks_for_a_partial_call_stays_documented_partial(
        self, schema: dict[str, Any], author: Author
    ) -> None:
        documented = _body(schema, "/routed/{id}/")
        assert documented == {"$ref": "#/components/schemas/PatchedTitleIn"}
        assert APIClient().patch(f"/routed/{author.pk}/", {}, format="json").status_code == 204


@pytest.mark.urls(__name__)
@pytest.mark.django_db
class TestAVariantOfADecoratedAction:
    def test_each_variant_is_documented_whole_as_the_wire_demands(
        self, schema: dict[str, Any], author: Author
    ) -> None:
        members = _resolved(schema, _body(schema, "/decorated/{id}/variants/"))["anyOf"]
        assert members == [
            {"$ref": "#/components/schemas/TitleIn"},
            {"$ref": "#/components/schemas/SlugIn"},
        ]
        # The discriminator chooses ``title``.
        response = APIClient().patch(f"/decorated/{author.pk}/variants/", {}, format="json")
        assert response.status_code == 400
        assert sorted(response.data) == _resolved(schema, members[0])["required"]

    def test_a_variant_declaring_partial_is_partial_beside_one_that_is_not(
        self, schema: dict[str, Any], author: Author
    ) -> None:
        members = _resolved(schema, _body(schema, "/decorated/{id}/partial-variant/"))["anyOf"]
        assert members[0] == {"$ref": "#/components/schemas/PatchedTitleIn"}
        assert members[1]["required"] == ["shade"]
        # The discriminator chooses ``title``, whose spec declares ``partial``.
        response = APIClient().patch(f"/decorated/{author.pk}/partial-variant/", {}, format="json")
        assert response.status_code == 204

    def test_one_action_by_put_and_patch_documents_one_body(self, schema: dict[str, Any]) -> None:
        put = _body(schema, "/decorated/{id}/both-methods/", "put")
        assert put == _body(schema, "/decorated/{id}/both-methods/", "patch")
        assert put == {"$ref": "#/components/schemas/Decorated_both_methods_Request"}
