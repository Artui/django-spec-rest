from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from django.conf import settings
from django.test import override_settings
from django.urls import URLPattern, path
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import extend_schema
from rest_framework.routers import SimpleRouter
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import (
    SelectorListMixin,
    SelectorRetrieveMixin,
    ServiceCreateMixin,
    ServiceCreateView,
    ServiceDestroyMixin,
    ServiceUpdateMixin,
    service_action,
)
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
        # drf-spectacular's own reading, where a declared mapping is the operation's every response.
        assert _responses(path("v/", view.as_view())) == {"/v/": {"404"}}

    def test_decorated_after_enable_openapi_documents_the_spec(self) -> None:
        enable_openapi()
        view = _decorated_view()
        assert _responses(path("v/", view.as_view())) == {"/v/": {"201", "400", "404"}}


def _method_decorated_view() -> type:
    class _View(ServiceCreateView):
        queryset = Author.objects.all()
        spec = _spec()

        @extend_schema(responses={404: ServiceNotFoundSerializer})
        def post(self, request: Any, *args: Any, **kwargs: Any) -> Any: ...

    return _View


def test_a_method_level_extend_schema_has_no_order() -> None:
    # Decorated under the documented default, which the method's schema subclasses.
    view = _method_decorated_view()
    enable_openapi()
    assert _responses(path("v/", view.as_view())) == {"/v/": {"201", "400", "404"}}


class _ActionViewSet(GenericViewSet):
    queryset = Author.objects.all()

    @service_action(_spec(), detail=False, methods=["post"])
    def approve(self, request: Any) -> Any: ...


class _ComposedViewSet(ServiceCreateMixin, GenericViewSet):
    """The recipe's viewset over ``GenericViewSet``, composed of the action mixins."""

    queryset = Author.objects.all()
    action_specs = {"create": _spec()}


class _GenericFirstViewSet(GenericViewSet, ServiceCreateMixin):
    """The same, with ``GenericViewSet`` listed before the mixin."""

    queryset = Author.objects.all()
    action_specs = {"create": _spec()}


def _routed(viewset: type, **attrs: Any) -> list[Any]:
    router = SimpleRouter()
    router.register("r", type(viewset.__name__, (viewset,), attrs), basename="r")
    return router.urls


@pytest.mark.parametrize(
    ("viewset", "route", "success"),
    [
        (_ActionViewSet, "/r/approve/", "200"),
        (_ComposedViewSet, "/r/", "201"),
        (_GenericFirstViewSet, "/r/", "201"),
    ],
    ids=[
        "a service_action on a plain viewset",
        "a viewset of the action mixins",
        "a viewset of the action mixins after GenericViewSet",
    ],
)
class TestAViewSetOfTheProjectsOwn:
    def test_documents_its_spec_on_the_package_s_schema(
        self, viewset: type, route: str, success: str
    ) -> None:
        enable_openapi()
        assert _responses(*_routed(viewset, schema=ServiceAutoSchema())) == {
            route: {success, "400"}
        }


@pytest.mark.parametrize(
    ("viewset", "route", "success"),
    [(_ActionViewSet, "/r/approve/", "200"), (_GenericFirstViewSet, "/r/", "201")],
    ids=[
        "a service_action on a plain viewset",
        "a viewset of the action mixins after GenericViewSet",
    ],
)
def test_a_viewset_with_no_mixin_before_generic_viewset_documents_nothing_of_its_spec(
    viewset: type, route: str, success: str
) -> None:
    """``GenericViewSet``'s own ``schema``, DRF's default, comes first in its MRO."""
    enable_openapi()
    assert _responses(*_routed(viewset)) == {route: {success}}


_BY_PK = Parameters.of(Parameter("pk", "integer", required=True))


def _list() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda: Author.objects.all(),
        permissions=(Unrestricted(),),
        presenter=SerializerPresenter(AuthorSerializer),
    )


def _retrieve() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
        reads=_BY_PK,
        permissions=(Unrestricted(),),
        presenter=SerializerPresenter(AuthorSerializer),
    )


def _on_a_row() -> ServiceSpec:
    return dataclasses.replace(
        _spec(),
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
            reads=_BY_PK,
        ),
    )


@pytest.mark.parametrize(
    ("mixin", "action", "spec"),
    [
        (ServiceCreateMixin, "create", _spec()),
        (ServiceUpdateMixin, "update", _on_a_row()),
        (ServiceDestroyMixin, "destroy", _on_a_row()),
        (SelectorListMixin, "list", _list()),
        (SelectorRetrieveMixin, "retrieve", _retrieve()),
    ],
    ids=lambda value: value.__name__ if isinstance(value, type) else None,
)
def test_a_mixin_listed_first_documents_its_spec_with_no_schema_of_its_own(
    mixin: type, action: str, spec: Any
) -> None:
    """Documented as with ``schema = ServiceAutoSchema()``, and not as drf-spectacular reads it."""
    enable_openapi()
    attrs = {"queryset": Author.objects.all(), "action_specs": {action: spec}}
    composed = type("_Composed", (mixin, GenericViewSet), attrs)
    generic_first = type("_GenericFirst", (GenericViewSet, mixin), attrs)
    documented = _paths(*_routed(composed))
    assert documented == _paths(*_routed(composed, schema=ServiceAutoSchema()))
    assert documented != _paths(*_routed(generic_first))


class _ProjectSchema(ServiceAutoSchema):
    """A project's own schema class, named as DRF's ``DEFAULT_SCHEMA_CLASS``."""


def test_a_mixin_listed_first_overrides_a_project_s_default_schema_class() -> None:
    """The mixin's ``ServiceAutoSchema`` wins over the default."""
    enable_openapi()
    attrs = {"queryset": Author.objects.all(), "action_specs": {"create": _spec()}}
    default = {"DEFAULT_SCHEMA_CLASS": f"{__name__}._ProjectSchema"}
    with override_settings(REST_FRAMEWORK={**settings.REST_FRAMEWORK, **default}):
        composed = type("_Composed", (ServiceCreateMixin, GenericViewSet), attrs)
        keeping = type(
            "_Keeping", (ServiceCreateMixin, GenericViewSet), {**attrs, "schema": _ProjectSchema()}
        )
        assert type(composed.schema) is ServiceAutoSchema
        assert type(keeping.schema) is _ProjectSchema


def _paths(*patterns: URLPattern) -> dict[str, Any]:
    return SchemaGenerator(patterns=list(patterns)).get_schema(request=None, public=True)["paths"]
