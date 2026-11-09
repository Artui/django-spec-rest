"""``ServiceAutoSchema`` documenting a ``DiscriminatedAction``, end to end through drf-spectacular.

The request is one component, ``{View}_{action}_Request``, an ``anyOf`` over the
bodies of the variants that take one; the responses are the variants' merged
per status. Every route here is built from variants named for what they take,
so the expected component reads off the test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jsonschema
import pytest
from django.urls import path, re_path
from django_service_specs import (
    DataclassValidator,
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator
from rest_framework import serializers
from rest_framework.routers import DefaultRouter
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import ServiceViewSet, service_action
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.types.discriminated_action import DiscriminatedAction
from tests.testapp.models import Author

_OPEN = (Unrestricted(),)
_BY_PK = Parameters.of(Parameter("pk", "integer", required=True))


class AIn(serializers.Serializer):
    alpha = serializers.CharField()


class BIn(serializers.Serializer):
    beta = serializers.IntegerField()


class TenantIn(serializers.Serializer):
    """Every field is a capture of the route, which outranks the body, so nothing is left for it."""

    tenant = serializers.CharField()


class ReasonIn(serializers.Serializer):
    reason = serializers.CharField()


class AOut(serializers.Serializer):
    a = serializers.CharField()


class BOut(serializers.Serializer):
    b = serializers.IntegerField()


@dataclass
class Row:
    sku: str


class _Deny(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return False


def _service(**_: Any) -> None: ...


def _target() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
        reads=_BY_PK,
    )


def _spec(validator: Any = None, presenter: Any = None, **fields: Any) -> ServiceSpec:
    return ServiceSpec(
        **{
            "service": _service,
            "permissions": _OPEN,
            "validator": validator,
            "presenter": presenter,
            "allow_none": presenter is None,
            **fields,
        }
    )


def _on_a_row(validator: Any = None, presenter: Any = None, **fields: Any) -> ServiceSpec:
    return _spec(validator, presenter, instance_selector_spec=_target(), **fields)


def _pick() -> str:
    raise AssertionError("the schema never runs the discriminator")


def _action(**variants: ServiceSpec) -> DiscriminatedAction:
    return DiscriminatedAction(_pick, variants)


def _viewset(name: str, key: str, entry: Any) -> type:
    return type(
        name, (ServiceViewSet,), {"queryset": Author.objects.all(), "action_specs": {key: entry}}
    )


A_OUT = SerializerPresenter(AOut)
B_OUT = SerializerPresenter(BOut)

# A body-less variant beside two that take one, each answering its own body.
MIXED = _viewset(
    "Mixed",
    "create",
    _action(
        a=_spec(SerializerValidator(AIn), A_OUT),
        b=_spec(SerializerValidator(BIn), B_OUT),
        c=_spec(None, A_OUT),
    ),
)
# Two variants taking different bodies and answering the same one.
AGREE = _viewset(
    "Agree",
    "create",
    _action(a=_spec(SerializerValidator(AIn), A_OUT), b=_spec(SerializerValidator(BIn), A_OUT)),
)
# One variant presents a body and the other presents nothing.
HALF = _viewset(
    "Half",
    "create",
    _action(a=_spec(SerializerValidator(AIn), A_OUT), b=_spec(SerializerValidator(BIn))),
)
# Two variants taking one body: one member, since a second would say nothing more.
SAME = _viewset(
    "Same",
    "create",
    _action(a=_spec(SerializerValidator(AIn), A_OUT), b=_spec(SerializerValidator(AIn), B_OUT)),
)
# Every variant takes nothing, and none declares a Validator or a check.
BARE = _viewset("Bare", "create", _action(a=_spec(), b=_spec()))
# A variant with a body that is no serializer: a CSV upload's array of rows.
CSV = _viewset(
    "Csv",
    "create",
    _action(
        sheet=_spec(DataclassValidator(Row), None, many=True),
        form=_spec(SerializerValidator(AIn)),
    ),
)
# A many variant over a serializer is a list of its rows.
ROWS = _viewset(
    "Rows",
    "create",
    _action(
        rows=_spec(SerializerValidator(AIn), None, many=True), one=_spec(SerializerValidator(BIn))
    ),
)
# One variant's whole body is a capture of the route, which outranks the body.
READS = _viewset(
    "Reads",
    "create",
    _action(
        a=_spec(SerializerValidator(AIn), A_OUT),
        b=_spec(SerializerValidator(TenantIn), B_OUT),
    ),
)
# Every variant's only body is that capture: OPTIONS then describes a body-less spec.
ONLY_READS = _viewset("OnlyReads", "create", _action(a=_spec(SerializerValidator(TenantIn), A_OUT)))
PATCHED = _viewset(
    "Patched",
    "partial_update",
    _action(a=_on_a_row(SerializerValidator(AIn)), b=_on_a_row(SerializerValidator(BIn))),
)
DESTROYED = _viewset(
    "Destroyed",
    "destroy",
    _action(
        reason=_on_a_row(SerializerValidator(ReasonIn)),
        plain=_on_a_row(),
    ),
)
# One variant refuses every caller, so its 403 is documented beside the open one's.
GUARDED = _viewset(
    "Guarded",
    "create",
    _action(
        open=_spec(SerializerValidator(AIn), A_OUT),
        shut=_spec(SerializerValidator(BIn), A_OUT, permissions=(_Deny(),)),
    ),
)
# A variant with a service error declared documents the 422.
UNPROCESSABLE = _viewset(
    "Unprocessable",
    "create",
    _action(
        a=_spec(SerializerValidator(AIn), A_OUT),
        b=_spec(SerializerValidator(BIn), A_OUT, metadata={"document_service_error": True}),
    ),
)


# No ``queryset``, so drf-spectacular finds no model to type ``shelf`` by: only
# the second variant reads it, and the capture is typed from that read.
SHELVED = type(
    "Shelved",
    (ServiceViewSet,),
    {
        "action_specs": {
            "create": _action(
                a=_spec(SerializerValidator(AIn)),
                b=_spec(
                    SerializerValidator(BIn),
                    reads=Parameters.of(Parameter("shelf", "integer", required=True)),
                ),
            )
        }
    },
)


# No ``queryset`` here either, and both variants read ``shelf``: the first's type stands.
SHELVED_TWICE = type(
    "ShelvedTwice",
    (ServiceViewSet,),
    {
        "action_specs": {
            "create": _action(
                a=_spec(
                    SerializerValidator(AIn),
                    reads=Parameters.of(Parameter("shelf", "integer", required=True)),
                ),
                b=_spec(
                    SerializerValidator(BIn),
                    reads=Parameters.of(Parameter("shelf", "string", required=True)),
                ),
            )
        }
    },
)


class Decorated(GenericViewSet):
    queryset = Author.objects.all()

    @service_action(
        _action(a=_spec(SerializerValidator(AIn), A_OUT), b=_spec(SerializerValidator(BIn), B_OUT)),
        detail=False,
        methods=["post"],
    )
    def login(self, request: Any) -> Any: ...


_router = DefaultRouter()
_router.register("decorated", Decorated, basename="decorated")

urlpatterns = [
    path("mixed/", MIXED.as_view({"post": "create"})),
    path("agree/", AGREE.as_view({"post": "create"})),
    path("same/", SAME.as_view({"post": "create"})),
    path("half/", HALF.as_view({"post": "create"})),
    path("bare/", BARE.as_view({"post": "create"})),
    path("csv/", CSV.as_view({"post": "create"})),
    path("rows/", ROWS.as_view({"post": "create"})),
    path("reads/<str:tenant>/", READS.as_view({"post": "create"})),
    path("only-reads/<str:tenant>/", ONLY_READS.as_view({"post": "create"})),
    path("patched/<int:pk>/", PATCHED.as_view({"patch": "partial_update"})),
    path("destroyed/<int:pk>/", DESTROYED.as_view({"delete": "destroy"})),
    path("guarded/", GUARDED.as_view({"post": "create"})),
    path("unprocessable/", UNPROCESSABLE.as_view({"post": "create"})),
    re_path(r"^shelved/(?P<shelf>[^/.]+)/$", SHELVED.as_view({"post": "create"})),
    re_path(r"^shelved-twice/(?P<shelf>[^/.]+)/$", SHELVED_TWICE.as_view({"post": "create"})),
    *_router.urls,
]


@pytest.fixture(scope="module", autouse=True)
def _enable_openapi() -> None:
    enable_openapi()


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)


def _op(schema: dict[str, Any], route: str, method: str) -> dict[str, Any]:
    return schema["paths"][route][method]


def _body(schema: dict[str, Any], route: str, method: str) -> dict[str, Any]:
    return _op(schema, route, method)["requestBody"]["content"]["application/json"]["schema"]


def _component(schema: dict[str, Any], ref: dict[str, Any]) -> dict[str, Any]:
    return schema["components"]["schemas"][ref["$ref"].rsplit("/", 1)[1]]


def _request(schema: dict[str, Any], route: str, method: str = "post") -> dict[str, Any]:
    """The ``anyOf`` the operation's request body names."""
    return _component(schema, _body(schema, route, method))


def _response(schema: dict[str, Any], route: str, method: str, status: str) -> dict[str, Any]:
    return _op(schema, route, method)["responses"][status]["content"]["application/json"]["schema"]


def _options(view: Any, method: str, **captures: Any) -> dict[str, Any]:
    response = view(APIRequestFactory().options("/"), **captures)
    return response.data["actions"][method]


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


class TestTheRequestComponent:
    def test_it_is_named_for_the_view_and_the_action(self, schema: dict[str, Any]) -> None:
        assert _body(schema, "/mixed/", "post") == _ref("Mixed_create_Request")
        assert _body(schema, "/decorated/login/", "post") == _ref("Decorated_login_Request")
        assert _body(schema, "/patched/{id}/", "patch") == _ref("Patched_partial_update_Request")

    def test_it_is_a_any_of_over_the_variants_bodies(self, schema: dict[str, Any]) -> None:
        assert _request(schema, "/mixed/") == {"anyOf": [_ref("AIn"), _ref("BIn")]}

    def test_variants_taking_one_body_add_it_once(self, schema: dict[str, Any]) -> None:
        assert _request(schema, "/same/") == {"anyOf": [_ref("AIn")]}

    def test_a_variant_with_no_body_adds_no_member(self, schema: dict[str, Any]) -> None:
        # ``c`` takes nothing: an empty member would match every body.
        assert len(_request(schema, "/mixed/")["anyOf"]) == 2
        assert {} not in _request(schema, "/mixed/")["anyOf"]

    def test_it_is_never_an_empty_any_of(self, schema: dict[str, Any]) -> None:
        assert "requestBody" not in _op(schema, "/bare/", "post")
        assert not any(
            component.get("anyOf") == [] for component in schema["components"]["schemas"].values()
        )
        assert "Bare_create_Request" not in schema["components"]["schemas"]

    def test_a_variant_with_a_body_and_no_serializer_is_documented(
        self, schema: dict[str, Any]
    ) -> None:
        sheet, form = _request(schema, "/csv/")["anyOf"]
        assert sheet["type"] == "array"
        assert set(sheet["items"]["properties"]) == {"sku"}
        assert form == _ref("AIn")

    def test_a_many_serializer_variant_is_a_list_of_its_rows(self, schema: dict[str, Any]) -> None:
        assert _request(schema, "/rows/")["anyOf"] == [
            {"type": "array", "items": _ref("AIn")},
            _ref("BIn"),
        ]

    def test_a_patch_names_the_partial_form_of_each_variant(self, schema: dict[str, Any]) -> None:
        assert _request(schema, "/patched/{id}/", "patch") == {
            "anyOf": [_ref("PatchedAIn"), _ref("PatchedBIn")]
        }

    def test_a_delete_documents_the_body_it_takes(self, schema: dict[str, Any]) -> None:
        assert _request(schema, "/destroyed/{id}/", "delete") == {"anyOf": [_ref("ReasonIn")]}

    def test_a_decorated_action_is_documented_too(self, schema: dict[str, Any]) -> None:
        assert _request(schema, "/decorated/login/") == {"anyOf": [_ref("AIn"), _ref("BIn")]}


@pytest.fixture
def warned(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The warnings drf-spectacular is asked to emit, which it prints once and then caches."""
    emitted: list[str] = []

    def emit(message: str, severity: str) -> None:
        if severity == "warning":
            emitted.append(message)

    monkeypatch.setattr(GENERATOR_STATS, "emit", emit)
    return emitted


@dataclass
class Member:
    org: str
    name: str


def _generate(*patterns: Any) -> dict[str, Any]:
    return SchemaGenerator(patterns=list(patterns)).get_schema(request=None, public=True)


class TestOneNameForTwoBodies:
    """A component name two operations share, whose bodies differ, never takes the schema down."""

    def test_two_classes_of_one_name_each_document_their_own_body(self, warned: list[str]) -> None:
        first = _viewset("ProjectViewSet", "create", _action(a=_spec(SerializerValidator(AIn))))
        second = _viewset("ProjectViewSet", "create", _action(a=_spec(SerializerValidator(BIn))))
        first.__module__, second.__module__ = "api.v1", "api.v2"
        schema = _generate(
            path("v1/", first.as_view({"post": "create"})),
            path("v2/", second.as_view({"post": "create"})),
        )
        assert _request(schema, "/v1/") == {"anyOf": [_ref("AIn")]}
        assert _body(schema, "/v2/", "post") == {"anyOf": [_ref("BIn")]}
        assert len(warned) == 1
        assert "ProjectViewSet_create_Request" in warned[0]

    def test_a_route_capture_named_as_a_field_changes_the_body_it_documents(
        self, warned: list[str]
    ) -> None:
        view = _viewset("Nested", "create", _action(a=_spec(DataclassValidator(Member))))
        schema = _generate(
            path("q/", view.as_view({"post": "create"})),
            path("orgs/<str:org>/q/", view.as_view({"post": "create"})),
        )
        # The route sorted first holds the component, and the other is inline.
        held, inline = _body(schema, "/orgs/{org}/q/", "post"), _body(schema, "/q/", "post")
        assert held == _ref("Nested_create_Request")
        captured, bare = _component(schema, held)["anyOf"], inline["anyOf"]
        assert [set(m["properties"]) for m in bare] == [{"org", "name"}]
        assert [set(m["properties"]) for m in captured] == [{"name"}]
        assert len(warned) == 1

    def test_two_operations_of_one_body_share_the_component_without_a_warning(
        self, warned: list[str]
    ) -> None:
        view = _viewset("Shared", "create", _action(a=_spec(SerializerValidator(AIn))))
        schema = _generate(
            path("one/", view.as_view({"post": "create"})),
            path("two/", view.as_view({"post": "create"})),
        )
        assert _body(schema, "/one/", "post") == _ref("Shared_create_Request")
        assert _body(schema, "/two/", "post") == _ref("Shared_create_Request")
        assert warned == []


class TestThePathParameters:
    def test_a_capture_is_typed_by_the_read_of_any_variant(self, schema: dict[str, Any]) -> None:
        (parameter,) = _op(schema, "/shelved/{shelf}/", "post")["parameters"]
        assert (parameter["name"], parameter["schema"]) == ("shelf", {"type": "integer"})

    def test_a_capture_two_variants_read_is_typed_by_the_first(
        self, schema: dict[str, Any]
    ) -> None:
        (parameter,) = _op(schema, "/shelved-twice/{shelf}/", "post")["parameters"]
        assert (parameter["name"], parameter["schema"]) == ("shelf", {"type": "integer"})


class TestTheRequestAgreesWithOptions:
    def test_each_member_is_a_variant_options_describes(self, schema: dict[str, Any]) -> None:
        members = _options(MIXED.as_view({"post": "create"}), "POST")["anyOf"]
        documented = [_component(schema, ref) for ref in _request(schema, "/mixed/")["anyOf"]]
        assert [set(m["properties"]) for m in members] == [{"alpha"}, {"beta"}]
        assert [set(m["properties"]) for m in documented] == [{"alpha"}, {"beta"}]
        assert [m.get("required") for m in members] == [m.get("required") for m in documented]

    @pytest.mark.django_db
    def test_a_body_two_variants_accept_is_valid_for_what_both_document(
        self, schema: dict[str, Any]
    ) -> None:
        # A member's schema is open, since the edge drops a key it does not
        # know, so this body matches both. The wire accepts it; a ``oneOf``
        # would document it as invalid.
        body = {"alpha": "x", "beta": 1}
        view = _viewset(
            "AcceptsBoth",
            "create",
            DiscriminatedAction(
                lambda: "a",
                {"a": _spec(SerializerValidator(AIn)), "b": _spec(SerializerValidator(BIn))},
            ),
        ).as_view({"post": "create"})
        assert view(APIRequestFactory().post("/", body, format="json")).status_code == 204
        documented = {**_request(schema, "/mixed/"), "components": schema["components"]}
        jsonschema.validate(body, documented)
        jsonschema.validate(body, _options(MIXED.as_view({"post": "create"}), "POST"))

    def test_variants_taking_one_body_are_one_member_in_both(self, schema: dict[str, Any]) -> None:
        members = _options(SAME.as_view({"post": "create"}), "POST")["anyOf"]
        assert [set(m["properties"]) for m in members] == [{"alpha"}]
        assert _request(schema, "/same/")["anyOf"] == [_ref("AIn")]

    def test_a_variant_whose_every_field_is_a_route_capture_is_in_neither(
        self, schema: dict[str, Any]
    ) -> None:
        view = READS.as_view({"post": "create"})
        described = _options(view, "POST", tenant="t")["anyOf"]
        assert [set(m["properties"]) for m in described] == [{"alpha"}]
        assert _request(schema, "/reads/{tenant}/") == {"anyOf": [_ref("AIn")]}

    def test_every_variant_taking_nothing_is_a_plain_body_less_spec_in_both(
        self, schema: dict[str, Any]
    ) -> None:
        described = _options(ONLY_READS.as_view({"post": "create"}), "POST", tenant="t")
        assert described["properties"] == {}
        assert "anyOf" not in described
        assert "requestBody" not in _op(schema, "/only-reads/{tenant}/", "post")
        assert "OnlyReads_create_Request" not in schema["components"]["schemas"]

    def test_a_many_member_is_the_list_options_keeps_as_its_one_property(
        self, schema: dict[str, Any]
    ) -> None:
        members = _options(ROWS.as_view({"post": "create"}), "POST")["anyOf"]
        listed = members[0]["properties"]
        assert list(listed) == ["items"]
        assert _component(schema, _body(schema, "/rows/", "post"))["anyOf"][0] == {
            "type": "array",
            "items": _ref("AIn"),
        }
        assert listed["items"]["type"] == "array"
        assert listed["items"]["items"]["properties"].keys() == {"alpha"}


class TestTheResponses:
    def test_variants_that_agree_are_one_body(self, schema: dict[str, Any]) -> None:
        assert _response(schema, "/agree/", "post", "201") == _ref("AOut")

    def test_variants_that_differ_are_an_inline_any_of(self, schema: dict[str, Any]) -> None:
        # ``c`` answers ``AOut`` as ``a`` does, so it is named once.
        assert _response(schema, "/mixed/", "post", "201") == {
            "anyOf": [_ref("AOut"), _ref("BOut")]
        }

    def test_a_status_one_variant_answers_is_that_variant_s(self, schema: dict[str, Any]) -> None:
        responses = _op(schema, "/guarded/", "post")["responses"]
        assert set(responses) == {"201", "400", "403"}
        assert _response(schema, "/guarded/", "post", "403") == _ref("PermissionDenied")
        assert _response(schema, "/unprocessable/", "post", "422") == _ref("ServiceError")

    def test_a_400_is_documented_whatever_the_variants_declare(
        self, schema: dict[str, Any]
    ) -> None:
        # No variant of ``Bare`` declares a Validator: the discriminator may
        # still refuse, as a 400.
        bare = _op(schema, "/bare/", "post")["responses"]
        mixed = _op(schema, "/mixed/", "post")["responses"]
        assert bare["400"] == mixed["400"]
        assert "anyOf" in bare["400"]["content"]["application/json"]["schema"]

    def test_a_variant_presenting_nothing_answers_its_own_204_beside_the_body(
        self, schema: dict[str, Any]
    ) -> None:
        responses = _op(schema, "/half/", "post")["responses"]
        assert _response(schema, "/half/", "post", "201") == _ref("AOut")
        assert set(responses) == {"201", "204", "400"}
        assert "content" not in responses["204"]

    def test_nothing_presented_by_any_variant_is_no_body_at_either_status(
        self, schema: dict[str, Any]
    ) -> None:
        # A variant's service may return a value as well as nothing, and
        # with no presenter a document cannot tell which one a call answers.
        responses = _op(schema, "/bare/", "post")["responses"]
        assert set(responses) == {"201", "204", "400"}
        assert "content" not in responses["201"]
        assert "content" not in responses["204"]
