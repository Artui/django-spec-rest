"""A project's ``@extend_schema(responses=...)`` is added to what the spec documents.

drf-spectacular answers a declared ``responses`` as it is, which would drop the
body, the 400, the 403 and the 422 the spec documents for the refusals a project
declares. A mapping of statuses is laid over the spec's instead: a status
declared replaces the spec's at that status, and a declared success replaces
every success the spec documents. Held on each surface a project decorates: a
standalone view's class and its method, a viewset's action through
``extend_schema_view``, and a ``@service_action``.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.urls import path
from django_service_specs import (
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
)
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import (
    SelectorListView,
    ServiceCreateView,
    ServiceViewSet,
    service_action,
)
from django_spec_rest.openapi import (
    ServiceConflictSerializer,
    ServiceNotFoundSerializer,
    enable_openapi,
)
from django_spec_rest.openapi.service_auto_schema import ServiceAutoSchema
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.openapi.test_validator_refusal_schema import _Person
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

# ``extend_schema`` on a class subclasses the schema the class has when it is
# decorated, so the package's schema is set first, as a project's
# ``AppConfig.ready()`` sets it before its URLconf imports its views.
enable_openapi()


class _Members(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True


def _write() -> ServiceSpec:
    return ServiceSpec(
        service=lambda **_: None,
        permissions=(_Members(),),
        validator=SerializerValidator(_Person),
        presenter=SerializerPresenter(AuthorSerializer),
    )


def _read() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda: Author.objects.all(),
        permissions=(_Members(),),
        presenter=SerializerPresenter(AuthorSerializer),
    )


def _view(base: type, responses: Any, **attrs: Any) -> type:
    return extend_schema(responses=responses, **attrs.pop("extend", {}))(
        type("_View", (base,), {"queryset": Author.objects.all(), "spec": _write(), **attrs})
    )


_NOT_FOUND = {404: ServiceNotFoundSerializer}


class _MethodView(ServiceCreateView):
    queryset = Author.objects.all()
    spec = _write()

    @extend_schema(responses={409: ServiceConflictSerializer})
    def post(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        return super().post(request, *args, **kwargs)


@extend_schema_view(create=extend_schema(responses=_NOT_FOUND))
class _ViewSet(ServiceViewSet):
    queryset = Author.objects.all()
    action_specs = {"create": _write()}


class _ActionViewSet(GenericViewSet):
    queryset = Author.objects.all()

    @extend_schema(responses=_NOT_FOUND)
    @service_action(_write(), detail=False, methods=["post"])
    def approve(self, request: Any) -> Any: ...


class _Plain(APIView):
    """A view no spec documents, on the package's schema."""

    schema = ServiceAutoSchema()

    @extend_schema(responses={200: AuthorSerializer})
    def get(self, request: Any) -> Response:
        return Response()


_router = DefaultRouter()
_router.register("authors", _ViewSet, basename="authors")
_router.register("actions", _ActionViewSet, basename="actions")

urlpatterns = [
    path("class/", _view(ServiceCreateView, _NOT_FOUND).as_view()),
    path("method/", _MethodView.as_view()),
    path(
        "read/",
        extend_schema(responses=_NOT_FOUND)(
            type("_Read", (SelectorListView,), {"spec": _read()})
        ).as_view(),
    ),
    path("bare/", _view(ServiceCreateView, ServiceNotFoundSerializer).as_view()),
    path(
        "string/",
        _view(ServiceCreateView, {"422": OpenApiResponse(description="Declared.")}).as_view(),
    ),
    path("success/", _view(ServiceCreateView, {200: ServiceNotFoundSerializer}).as_view()),
    path(
        "tuple/",
        _view(
            ServiceCreateView,
            {
                (403, "application/json"): OpenApiResponse(
                    ServiceNotFoundSerializer, description="Declared."
                )
            },
        ).as_view(),
    ),
    # Declared for a method the route does not serve.
    path("scoped/", _view(ServiceCreateView, _NOT_FOUND, extend={"methods": ["PUT"]}).as_view()),
    path("plain/", _Plain.as_view()),
    *_router.urls,
]

# What ``_write()`` documents with nothing declared: the create's body, the
# Validator's 400, the check's 403 and the 422.
_OWN = {"201", "400", "403", "422"}


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)


def _responses(schema: dict[str, Any], route: str, method: str = "post") -> dict[str, Any]:
    return schema["paths"][route][method]["responses"]


def _ref(response: dict[str, Any]) -> str:
    return response["content"]["application/json"]["schema"]["$ref"]


class TestADeclaredRefusalIsAddedToTheSpecSResponses:
    @pytest.mark.parametrize(
        ("route", "success"),
        [("/class/", "201"), ("/authors/", "201"), ("/actions/approve/", "200")],
    )
    def test_a_declared_refusal_is_added_to_the_spec_s_responses(
        self, schema: dict[str, Any], route: str, success: str
    ) -> None:
        responses = _responses(schema, route)
        assert set(responses) == {success, "400", "403", "404", "422"}
        assert _ref(responses["404"]) == "#/components/schemas/ServiceNotFound"
        assert _ref(responses[success]) == "#/components/schemas/Author"

    def test_on_a_method(self, schema: dict[str, Any]) -> None:
        responses = _responses(schema, "/method/")
        assert set(responses) == _OWN | {"409"}
        assert _ref(responses["409"]) == "#/components/schemas/ServiceConflict"

    def test_on_a_selector(self, schema: dict[str, Any]) -> None:
        assert set(_responses(schema, "/read/", "get")) == {"200", "403", "404", "422"}

    def test_a_tuple_of_status_and_media_type_replaces_the_spec_s(
        self, schema: dict[str, Any]
    ) -> None:
        responses = _responses(schema, "/tuple/")
        assert set(responses) == _OWN
        assert responses["403"]["description"] == "Declared."
        assert _ref(responses["403"]) == "#/components/schemas/ServiceNotFound"

    def test_out_of_scope_the_spec_s_own_stand(self, schema: dict[str, Any]) -> None:
        assert set(_responses(schema, "/scoped/")) == _OWN


class TestADeclaredStatusReplacesTheSpecS:
    def test_a_status_declared_as_a_string_replaces_the_spec_s(
        self, schema: dict[str, Any]
    ) -> None:
        responses = _responses(schema, "/string/")
        assert set(responses) == _OWN
        assert responses["422"] == {"description": "Declared."}

    def test_a_declared_success_replaces_the_spec_s_successes(self, schema: dict[str, Any]) -> None:
        responses = _responses(schema, "/success/")
        assert set(responses) == {"200", "400", "403", "422"}
        assert _ref(responses["200"]) == "#/components/schemas/ServiceNotFound"


class TestWhatIsNoMappingOfStatuses:
    def test_a_bare_serializer_declared_is_the_success_body(self, schema: dict[str, Any]) -> None:
        # At the 201 the create answers with, where drf-spectacular alone
        # documents a view's ``POST`` as a 200.
        responses = _responses(schema, "/bare/")
        assert set(responses) == _OWN
        assert _ref(responses["201"]) == "#/components/schemas/ServiceNotFound"

    def test_a_view_no_spec_documents_is_drf_spectacular_s(self, schema: dict[str, Any]) -> None:
        responses = _responses(schema, "/plain/", "get")
        assert set(responses) == {"200"}
        assert _ref(responses["200"]) == "#/components/schemas/Author"
