"""A spec with no presenter answers ``204`` for a service returning nothing, and is documented at either.

The edge answers ``204`` only where the service returned ``None``, and the
kernel's ``present`` hands a value back as it is, so a document cannot tell
which one call answers: it lists the action's default status and the ``204``
both, beside a destroy's ``204`` alone and the one status a view sets. The
status is read off a real response beside the document's, so the two cannot
drift apart; the merged responses of a ``DiscriminatedAction`` list each status
any variant answers.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.urls import path
from django_service_specs import ServiceSpec, Unrestricted
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers
from rest_framework.routers import DefaultRouter
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import ServiceCreateView, ServiceViewSet, service_action
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.types.discriminated_action import DiscriminatedAction
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db

_OPEN = (Unrestricted(),)


class AIn(serializers.Serializer):
    alpha = serializers.CharField()


class Out(serializers.Serializer):
    a = serializers.CharField()


class Declared(serializers.Serializer):
    declared = serializers.CharField()


def _returns_a_row(**_: Any) -> dict[str, str]:
    return {"a": "x"}


def _nothing(**_: Any) -> None: ...


def _a_value(**_: Any) -> dict[str, bool]:
    return {"raw": True}


def _valued() -> ServiceSpec:
    """No presenter, a service returning a value: the edge answers the default, with the value."""
    return ServiceSpec(service=_a_value, permissions=_OPEN, atomic=False)


def _bare(**fields: Any) -> ServiceSpec:
    return ServiceSpec(service=_nothing, permissions=_OPEN, allow_none=True, **fields)


def _presenting() -> ServiceSpec:
    return ServiceSpec(
        service=_returns_a_row, permissions=_OPEN, presenter=SerializerPresenter(Out)
    )


def _status_callable() -> int:
    return 202


class Bare(ServiceCreateView):
    spec = _bare()


class Valued(ServiceCreateView):
    spec = _valued()


class ValuedAtAStatus(ServiceCreateView):
    spec = _valued()
    success_status = 202


@extend_schema(responses=Declared)
class ValuedAndDeclared(ServiceCreateView):
    spec = _valued()


class Declaring(ServiceCreateView):
    spec = _bare()
    success_status = 202


class Calling(ServiceCreateView):
    spec = _bare()
    success_status = staticmethod(_status_callable)


def _presenting_or_nothing() -> ServiceSpec:
    return ServiceSpec(
        service=_nothing,
        permissions=_OPEN,
        allow_none=True,
        presenter=SerializerPresenter(Out),
    )


class MayPresentNothing(ServiceCreateView):
    spec = _presenting_or_nothing()


class MayPresentNothingAtAStatus(ServiceCreateView):
    spec = _presenting_or_nothing()
    success_status = 202


class Plain(ServiceViewSet):
    queryset = Author.objects.all()
    action_specs = {"create": _bare()}


class ValuedPlain(ServiceViewSet):
    queryset = Author.objects.all()
    action_specs = {"create": _valued()}


class ValuedHalf(ServiceViewSet):
    """One variant returns a value and the other nothing, with no presenter on either."""

    queryset = Author.objects.all()
    action_specs = {
        "create": DiscriminatedAction(
            lambda request: request.query_params["pick"], {"a": _valued(), "b": _bare()}
        )
    }


class Half(ServiceViewSet):
    """One variant presents and the other does not, each answering its own status."""

    queryset = Author.objects.all()
    action_specs = {
        "create": DiscriminatedAction(
            lambda request: request.query_params["pick"], {"a": _presenting(), "b": _bare()}
        )
    }


class Silent(ServiceViewSet):
    """No variant presents, so no variant answers a body."""

    queryset = Author.objects.all()
    action_specs = {
        "create": DiscriminatedAction(
            lambda request: request.query_params["pick"], {"a": _bare(), "b": _bare()}
        )
    }


class AtOneStatus(ServiceViewSet):
    """A view's status over both, so a body and no body answer one status."""

    queryset = Author.objects.all()
    success_status = 201
    action_specs = {
        "create": DiscriminatedAction(
            lambda request: request.query_params["pick"], {"a": _bare(), "b": _presenting()}
        )
    }


@extend_schema_view(create=extend_schema(responses=Declared))
class DeclaredOverAFirstVariantWithNoBody(ServiceViewSet):
    """The success body a project declares is laid over the status a variant answers a body at."""

    queryset = Author.objects.all()
    action_specs = {
        "create": DiscriminatedAction(
            lambda request: request.query_params["pick"], {"b": _bare(), "a": _presenting()}
        )
    }


@extend_schema_view(create=extend_schema(responses=Declared))
class DeclaredOverSilence(ServiceViewSet):
    """No variant answers a body, so nothing a project declares is a success body."""

    queryset = Author.objects.all()
    action_specs = {
        "create": DiscriminatedAction(
            lambda request: request.query_params["pick"],
            {"a": _bare(validator=SerializerValidator(AIn)), "b": _bare()},
        )
    }


class Decorated(GenericViewSet):
    queryset = Author.objects.all()

    @service_action(_bare(), detail=False, methods=["post"])
    def run(self, request: Any) -> Any: ...


class ValuedDecorated(GenericViewSet):
    queryset = Author.objects.all()

    @service_action(_valued(), detail=False, methods=["post"])
    def run(self, request: Any) -> Any: ...


_router = DefaultRouter()
_router.register("decorated", Decorated, basename="decorated")
_router.register("valued-decorated", ValuedDecorated, basename="valued-decorated")

_CREATE = {"post": "create"}
urlpatterns = [
    path("bare/", Bare.as_view()),
    path("valued/", Valued.as_view()),
    path("valued-at-a-status/", ValuedAtAStatus.as_view()),
    path("valued-and-declared/", ValuedAndDeclared.as_view()),
    path("valued-plain/", ValuedPlain.as_view(_CREATE)),
    path("valued-half/", ValuedHalf.as_view(_CREATE)),
    path("declaring/", Declaring.as_view()),
    path("calling/", Calling.as_view()),
    path("may-present-nothing/", MayPresentNothing.as_view()),
    path("may-present-nothing-at-a-status/", MayPresentNothingAtAStatus.as_view()),
    path("plain/", Plain.as_view(_CREATE)),
    path("half/", Half.as_view(_CREATE)),
    path("silent/", Silent.as_view(_CREATE)),
    path("at-one-status/", AtOneStatus.as_view(_CREATE)),
    path("declared/", DeclaredOverAFirstVariantWithNoBody.as_view(_CREATE)),
    path("declared-over-silence/", DeclaredOverSilence.as_view(_CREATE)),
    *_router.urls,
]


@pytest.fixture(scope="module", autouse=True)
def _enable_openapi() -> None:
    enable_openapi()


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)


def _responses(schema: dict[str, Any], route: str) -> dict[str, Any]:
    return schema["paths"][route]["post"]["responses"]


def _post(view: Any, url: str = "/", **captures: Any) -> Any:
    return view(APIRequestFactory().post(url, {}, format="json"), **captures)


class TestASpecWithNoPresenter:
    @pytest.mark.parametrize(
        ("route", "view", "default"),
        [
            ("/bare/", Bare.as_view(), "201"),
            ("/plain/", Plain.as_view(_CREATE), "201"),
            ("/decorated/run/", Decorated.as_view({"post": "run"}), "200"),
        ],
        ids=["standalone", "viewset", "decorated"],
    )
    def test_it_answers_204_for_nothing_and_documents_it_beside_the_default(
        self, schema: dict[str, Any], route: str, view: Any, default: str
    ) -> None:
        assert _post(view).status_code == 204
        responses = _responses(schema, route)
        assert set(responses) == {default, "204"}
        assert "content" not in responses[default]
        assert "content" not in responses["204"]

    def test_a_status_the_view_sets_is_the_one_answered_and_documented(
        self, schema: dict[str, Any]
    ) -> None:
        assert _post(Declaring.as_view()).status_code == 202
        assert set(_responses(schema, "/declaring/")) == {"202"}
        assert "content" not in _responses(schema, "/declaring/")["202"]

    def test_a_callable_status_documents_the_action_s_default(self, schema: dict[str, Any]) -> None:
        # What it answers keys on the result, which no document can read.
        assert set(_responses(schema, "/calling/")) == {"201"}


class TestASpecWithNoPresenterReturningAValue:
    @pytest.mark.parametrize(
        ("route", "view", "answered", "also"),
        [
            ("/valued/", Valued.as_view(), "201", "204"),
            ("/valued-plain/", ValuedPlain.as_view(_CREATE), "201", "204"),
            (
                "/valued-decorated/run/",
                ValuedDecorated.as_view({"post": "run"}),
                "200",
                "204",
            ),
        ],
        ids=["standalone", "viewset", "decorated"],
    )
    def test_it_documents_the_status_it_answers_and_the_204_beside_it(
        self, schema: dict[str, Any], route: str, view: Any, answered: str, also: str
    ) -> None:
        response = _post(view)
        assert response.status_code == int(answered)
        assert response.data == {"raw": True}
        responses = _responses(schema, route)
        assert set(responses) == {answered, also}
        assert "content" not in responses[answered]
        assert "content" not in responses[also]

    def test_a_discriminated_action_lists_the_status_each_variant_may_answer(
        self, schema: dict[str, Any]
    ) -> None:
        view = ValuedHalf.as_view(_CREATE)
        valued = _post(view, "/?pick=a")
        assert (valued.status_code, valued.data) == (201, {"raw": True})
        assert _post(view, "/?pick=b").status_code == 204
        assert set(_responses(schema, "/valued-half/")) == {"201", "204", "400"}

    def test_a_status_the_view_sets_is_the_one_answered_and_documented(
        self, schema: dict[str, Any]
    ) -> None:
        response = _post(ValuedAtAStatus.as_view())
        assert (response.status_code, response.data) == (202, {"raw": True})
        assert set(_responses(schema, "/valued-at-a-status/")) == {"202"}

    def test_a_declared_success_body_lands_on_the_status_the_value_answers(
        self, schema: dict[str, Any]
    ) -> None:
        response = _post(ValuedAndDeclared.as_view())
        assert (response.status_code, response.data) == (201, {"raw": True})
        responses = _responses(schema, "/valued-and-declared/")
        assert responses["201"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/Declared"
        }
        # A declared success replaces every one the spec documents (``_merged``).
        assert "204" not in responses


class TestASpecThatMayPresentNothing:
    def test_with_no_status_set_it_documents_the_204_beside_the_body(
        self, schema: dict[str, Any]
    ) -> None:
        assert _post(MayPresentNothing.as_view()).status_code == 204
        responses = _responses(schema, "/may-present-nothing/")
        assert set(responses) == {"201", "204"}
        assert "content" in responses["201"]
        assert "content" not in responses["204"]

    def test_with_a_status_set_it_answers_that_status_and_never_a_204(
        self, schema: dict[str, Any]
    ) -> None:
        response = _post(MayPresentNothingAtAStatus.as_view())
        assert response.status_code == 202
        assert response.data is None
        responses = _responses(schema, "/may-present-nothing-at-a-status/")
        assert set(responses) == {"202"}
        assert "content" in responses["202"]


class TestTheVariantsMerged:
    def test_each_status_a_variant_answers_is_listed(self, schema: dict[str, Any]) -> None:
        view = Half.as_view(_CREATE)
        assert _post(view, "/?pick=a").status_code == 201
        assert _post(view, "/?pick=b").status_code == 204
        responses = _responses(schema, "/half/")
        assert set(responses) == {"201", "204", "400"}
        assert "content" in responses["201"]
        assert "content" not in responses["204"]

    def test_nothing_presented_by_any_variant_is_the_204_alone(
        self, schema: dict[str, Any]
    ) -> None:
        view = Silent.as_view(_CREATE)
        assert _post(view, "/?pick=a").status_code == 204
        assert _post(view, "/?pick=b").status_code == 204
        responses = _responses(schema, "/silent/")
        assert set(responses) == {"201", "204", "400"}
        assert "content" not in responses["204"]

    def test_a_body_beside_no_body_at_one_status_keeps_the_body(
        self, schema: dict[str, Any]
    ) -> None:
        view = AtOneStatus.as_view(_CREATE)
        assert _post(view, "/?pick=a").status_code == 201
        assert _post(view, "/?pick=b").status_code == 201
        responses = _responses(schema, "/at-one-status/")
        assert set(responses) == {"201", "400"}
        assert responses["201"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/Out"
        }

    def test_a_declared_success_body_goes_to_the_status_a_variant_answers_a_body_at(
        self, schema: dict[str, Any]
    ) -> None:
        # The first variant presents nothing, so its 204 leads the mapping: the
        # declared body is still the 201's, the only status a body goes out at.
        responses = _responses(schema, "/declared/")
        assert responses["201"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/Declared"
        }
        # A declared success replaces every one the spec documents (``_merged``).
        assert "204" not in responses

    def test_a_declared_success_body_lands_on_the_201_and_never_on_a_refusal(
        self, schema: dict[str, Any]
    ) -> None:
        # No variant presents, so the lead is the 201 a value answers at, and
        # the declared success replaces the 204 beside it (``_merged``).
        responses = _responses(schema, "/declared-over-silence/")
        assert set(responses) == {"201", "400"}
        assert responses["201"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/Declared"
        }
        assert responses["400"]["content"]["application/json"]["schema"] != {
            "$ref": "#/components/schemas/Declared"
        }


def test_a_validator_s_400_stays_beside_the_success_statuses(schema: dict[str, Any]) -> None:
    class WithValidator(ServiceCreateView):
        spec = _bare(validator=SerializerValidator(AIn))

    document = SchemaGenerator(patterns=[path("v/", WithValidator.as_view())]).get_schema(
        request=None, public=True
    )
    assert set(_responses(document, "/v/")) == {"201", "204", "400"}
