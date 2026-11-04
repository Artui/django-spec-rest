"""The schema under the setup ``docs/openapi.md`` gives a project.

There, DRF's ``DEFAULT_SCHEMA_CLASS`` stays drf-spectacular's ``AutoSchema`` and
``enable_openapi()`` sets ``ServiceAutoSchema`` on the library's view classes.
The rest of the suite points the default at ``ServiceAutoSchema`` itself, so it
cannot see what the docs warn of: the order a class-level ``@extend_schema``
meets ``enable_openapi()`` in, and a viewset of the project's own that inherits
none of the library's classes.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.urls import URLPattern, path
from django_service_specs import ServiceSpec, Unrestricted
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import extend_schema
from rest_framework.routers import SimpleRouter
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import ServiceCreateMixin, ServiceCreateView, service_action
from django_spec_rest.openapi import ServiceNotFoundSerializer, enable_openapi
from django_spec_rest.openapi.service_auto_schema import ServiceAutoSchema
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.usefixtures("documented_setup")


def _spec() -> ServiceSpec:
    return ServiceSpec(
        service=lambda **_: None,
        permissions=(Unrestricted(),),
        validator=SerializerValidator(AuthorSerializer),
        presenter=SerializerPresenter(AuthorSerializer),
    )


def _responses(*patterns: URLPattern) -> dict[str, set[str]]:
    """Each documented operation's statuses, by path."""
    schema = SchemaGenerator(patterns=list(patterns)).get_schema(request=None, public=True)
    return {
        route: set(operation["responses"])
        for route, operations in schema["paths"].items()
        for operation in operations.values()
    }


def _decorated_view() -> type:
    return extend_schema(responses={404: ServiceNotFoundSerializer})(
        type("_View", (ServiceCreateView,), {"queryset": Author.objects.all(), "spec": _spec()})
    )


class TestAClassLevelExtendSchema:
    def test_decorated_before_enable_openapi_documents_nothing_of_the_spec(self) -> None:
        view = _decorated_view()
        enable_openapi()
        # drf-spectacular's own reading, where a declared mapping is the
        # operation's every response: neither the spec's success nor its 400
        # and 422.
        assert _responses(path("v/", view.as_view())) == {"/v/": {"404"}}

    def test_decorated_after_enable_openapi_documents_the_spec(self) -> None:
        enable_openapi()
        view = _decorated_view()
        assert _responses(path("v/", view.as_view())) == {"/v/": {"201", "400", "404", "422"}}


def _method_decorated_view() -> type:
    class _View(ServiceCreateView):
        queryset = Author.objects.all()
        spec = _spec()

        @extend_schema(responses={404: ServiceNotFoundSerializer})
        def post(self, request: Any, *args: Any, **kwargs: Any) -> Any: ...

    return _View


def test_a_method_level_extend_schema_has_no_order() -> None:
    # Decorated under the documented default, which the method's schema
    # subclasses: drf-spectacular lays it over the class's schema when it
    # generates, so ``enable_openapi()`` may run after the decorator.
    view = _method_decorated_view()
    enable_openapi()
    assert _responses(path("v/", view.as_view())) == {"/v/": {"201", "400", "404", "422"}}


class _ActionViewSet(GenericViewSet):
    queryset = Author.objects.all()

    @service_action(_spec(), detail=False, methods=["post"])
    def approve(self, request: Any) -> Any: ...


class _ComposedViewSet(ServiceCreateMixin, GenericViewSet):
    """The recipe's viewset over ``GenericViewSet``, composed of the action mixins."""

    queryset = Author.objects.all()
    action_specs = {"create": _spec()}


def _routed(viewset: type, **attrs: Any) -> list[Any]:
    router = SimpleRouter()
    router.register("r", type(viewset.__name__, (viewset,), attrs), basename="r")
    return router.urls


@pytest.mark.parametrize(
    ("viewset", "route", "success"),
    [(_ActionViewSet, "/r/approve/", "200"), (_ComposedViewSet, "/r/", "201")],
    ids=["a service_action on a plain viewset", "a viewset of the action mixins"],
)
class TestAViewSetOfTheProjectsOwn:
    def test_documents_nothing_of_its_spec_on_drf_spectacular_s_schema(
        self, viewset: type, route: str, success: str
    ) -> None:
        # ``enable_openapi()`` sets no schema on ``GenericViewSet`` or on the
        # mixins, so the viewset keeps the default.
        enable_openapi()
        assert _responses(*_routed(viewset)) == {route: {success}}

    def test_documents_its_spec_on_the_package_s_schema(
        self, viewset: type, route: str, success: str
    ) -> None:
        enable_openapi()
        assert _responses(*_routed(viewset, schema=ServiceAutoSchema())) == {
            route: {success, "400", "422"}
        }
