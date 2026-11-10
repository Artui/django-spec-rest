from __future__ import annotations

import threading
from typing import Any

import pytest
from django.urls import path
from django_service_specs import (
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import (
    SelectorListView,
    ServiceCreateView,
    ServiceDeleteView,
    ServiceViewSet,
    service_action,
)
from django_spec_rest.openapi import (
    SERVICE_ERROR_METADATA_KEY,
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


def _open() -> ServiceSpec:
    """A spec documenting a 201 and its declared 422 only: no Validator, no check to refuse."""
    return ServiceSpec(
        service=lambda **_: None,
        permissions=(Unrestricted(),),
        presenter=SerializerPresenter(AuthorSerializer),
        metadata={SERVICE_ERROR_METADATA_KEY: True},
    )


class _WithoutUnprocessable(ServiceAutoSchema):
    """A project's schema that stops documenting the 422 a spec declares."""

    def get_response_serializers(self) -> Any:
        responses = super().get_response_serializers()
        if isinstance(responses, dict):
            responses.pop(422, None)
        return responses


_ExtendedSchema = type(
    "ExtendedSchema",
    (_WithoutUnprocessable,),
    {"get_response_serializers": lambda self: {204: OpenApiResponse(description="Named.")}},
)
"""A project's class that only shares drf-spectacular's local class's name."""


def _open_view(**attrs: Any) -> type:
    return type(
        "_View",
        (ServiceCreateView,),
        {"queryset": Author.objects.all(), "spec": _open(), **attrs},
    )


_DELETE = ServiceSpec(
    service=lambda **_: None,
    permissions=(Unrestricted(),),
    instance_selector_spec=SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Author.objects.get(pk=pk),
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
    ),
)

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
        _view(ServiceCreateView, {"403": OpenApiResponse(description="Declared.")}).as_view(),
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
    path(
        "media/",
        _view(
            ServiceCreateView,
            {
                (404, "application/json"): ServiceNotFoundSerializer,
                (404, "text/plain"): ServiceNotFoundSerializer,
            },
        ).as_view(),
    ),
    # Declared for a method the route does not serve.
    path("scoped/", _view(ServiceCreateView, _NOT_FOUND, extend={"methods": ["PUT"]}).as_view()),
    path("plain/", _Plain.as_view()),
    path("dropping/", _open_view(schema=_WithoutUnprocessable()).as_view()),
    path(
        "dropping-extended/",
        extend_schema(responses=_NOT_FOUND)(_open_view(schema=_WithoutUnprocessable())).as_view(),
    ),
    path("open/", _open_view().as_view()),
    path(
        "named/",
        extend_schema(responses=_NOT_FOUND)(_open_view(schema=_ExtendedSchema())).as_view(),
    ),
    path(
        "delete/<int:pk>/",
        extend_schema(responses=AuthorSerializer)(
            type(
                "_Delete", (ServiceDeleteView,), {"queryset": Author.objects.all(), "spec": _DELETE}
            )
        ).as_view(),
    ),
    *_router.urls,
]

# What ``_write()`` documents with nothing declared: the create's body, the
# Validator's 400 and the check's 403. It declares no 422.
_OWN = {"201", "400", "403"}


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
        assert set(responses) == {success, "400", "403", "404"}
        assert _ref(responses["404"]) == "#/components/schemas/ServiceNotFound"
        assert _ref(responses[success]) == "#/components/schemas/Author"

    def test_on_a_method(self, schema: dict[str, Any]) -> None:
        responses = _responses(schema, "/method/")
        assert set(responses) == _OWN | {"409"}
        assert _ref(responses["409"]) == "#/components/schemas/ServiceConflict"

    def test_on_a_selector(self, schema: dict[str, Any]) -> None:
        assert set(_responses(schema, "/read/", "get")) == {"200", "403", "404"}

    def test_a_tuple_of_status_and_media_type_replaces_the_spec_s(
        self, schema: dict[str, Any]
    ) -> None:
        responses = _responses(schema, "/tuple/")
        assert set(responses) == _OWN
        assert responses["403"]["description"] == "Declared."
        assert _ref(responses["403"]) == "#/components/schemas/ServiceNotFound"

    def test_one_status_declared_for_two_media_types_has_both(self, schema: dict[str, Any]) -> None:
        content = _responses(schema, "/media/")["404"]["content"]
        assert set(content) == {"application/json", "text/plain"}

    def test_out_of_scope_the_spec_s_own_stand(self, schema: dict[str, Any]) -> None:
        assert set(_responses(schema, "/scoped/")) == _OWN


class TestADeclaredStatusReplacesTheSpecS:
    def test_a_status_declared_as_a_string_replaces_the_spec_s(
        self, schema: dict[str, Any]
    ) -> None:
        responses = _responses(schema, "/string/")
        assert set(responses) == _OWN
        assert responses["403"] == {"description": "Declared."}

    def test_a_declared_success_replaces_the_spec_s_successes(self, schema: dict[str, Any]) -> None:
        responses = _responses(schema, "/success/")
        assert set(responses) == {"200", "400", "403"}
        assert _ref(responses["200"]) == "#/components/schemas/ServiceNotFound"


class TestWhatIsNoMappingOfStatuses:
    def test_a_bare_serializer_declared_is_the_success_body(self, schema: dict[str, Any]) -> None:
        # At the 201 the create answers with.
        responses = _responses(schema, "/bare/")
        assert set(responses) == _OWN
        assert _ref(responses["201"]) == "#/components/schemas/ServiceNotFound"

    def test_a_view_no_spec_documents_is_drf_spectacular_s(self, schema: dict[str, Any]) -> None:
        responses = _responses(schema, "/plain/", "get")
        assert set(responses) == {"200"}
        assert _ref(responses["200"]) == "#/components/schemas/Author"


class TestAProjectSSchemaSubclassKeepsItsCustomisation:
    """Only drf-spectacular's ``extend_schema`` subclass is merged over the spec's responses."""

    def test_a_subclass_dropping_a_status_keeps_it_dropped(self, schema: dict[str, Any]) -> None:
        # Without ``extend_schema`` there is nothing to merge.
        assert sorted(_responses(schema, "/dropping/")) == ["201"]

    def test_and_so_does_one_under_a_class_level_extend_schema(
        self, schema: dict[str, Any]
    ) -> None:
        # The merge reads the subclass's answer, not ``ServiceAutoSchema``'s.
        assert sorted(_responses(schema, "/dropping-extended/")) == ["201", "404"]

    def test_a_project_class_named_for_it_is_not_extend_schema_s(
        self, schema: dict[str, Any]
    ) -> None:
        # Beneath extend_schema's own class, the project's is the base the 404 is laid over.
        assert sorted(_responses(schema, "/named/")) == ["204", "404"]

    def test_the_schema_with_no_such_subclass_documents_the_422(
        self, schema: dict[str, Any]
    ) -> None:
        assert sorted(_responses(schema, "/open/")) == ["201", "422"]


class TestABareSerializerOnANoContentRoute:
    def test_keeps_the_no_content_204(self, schema: dict[str, Any]) -> None:
        # The edge sends no body with a 204.
        responses = _responses(schema, "/delete/{id}/", "delete")
        assert responses["204"] == {"description": "No response body"}


class TestConcurrentGeneration:
    def test_one_shared_class_level_schema_renders_in_two_threads(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ``extend_schema`` on a class leaves one ``ExtendedSchema`` on it.
        view = extend_schema(responses=_NOT_FOUND)(_open_view())
        patterns = [path("race/", view.as_view())]
        SchemaGenerator(patterns=patterns).get_schema(request=None, public=True)
        barrier = threading.Barrier(2, timeout=5)
        waited = threading.local()
        render = AutoSchema._get_response_for_code
        errors: list[BaseException] = []

        def meet(self: Any, *args: Any, **kwargs: Any) -> Any:
            # Each thread meets the other once, inside its first render.
            if not getattr(waited, "done", False):
                waited.done = True
                barrier.wait()
            return render(self, *args, **kwargs)

        def generate() -> None:
            try:
                SchemaGenerator(patterns=patterns).get_schema(request=None, public=True)
            except BaseException as error:  # noqa: BLE001 - reported below
                errors.append(error)

        monkeypatch.setattr(AutoSchema, "_get_response_for_code", meet)
        threads = [threading.Thread(target=generate) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
