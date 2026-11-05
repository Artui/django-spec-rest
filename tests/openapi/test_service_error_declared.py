"""The ``422`` of a plain ``ServiceError`` is documented only where a spec declares it.

The edge answers a plain ``ServiceError`` 422, from the service, the selector,
a precondition or a provider, and the schema cannot see which specs raise one.
So a spec declares it, ``metadata={"document_service_error": True}``, and is
documented with it on every surface that serves it; a spec declaring nothing,
or ``False``, is documented without it. A project answering for many
operations at once overrides ``ServiceAutoSchema.documents_service_error``, a
public method, with nothing private imported.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import path
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
from rest_framework.routers import DefaultRouter
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import (
    SelectorListView,
    SelectorRetrieveView,
    SelectorViewSet,
    ServiceCreateView,
    ServiceUpdateView,
    ServiceViewSet,
    selector_action,
    service_action,
)
from django_spec_rest.openapi import (
    SERVICE_ERROR_METADATA_KEY,
    ServiceErrorSerializer,
    enable_openapi,
)
from django_spec_rest.openapi.service_auto_schema import ServiceAutoSchema
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

enable_openapi()

_DECLARED = {SERVICE_ERROR_METADATA_KEY: True}


def _write(metadata: Any = None) -> ServiceSpec:
    return ServiceSpec(
        service=lambda **_: None,
        permissions=(Unrestricted(),),
        presenter=SerializerPresenter(AuthorSerializer),
        metadata=metadata,
    )


def _read(metadata: Any = None, kind: SelectorKind = SelectorKind.LIST) -> SelectorSpec:
    return SelectorSpec(
        kind=kind,
        selector=lambda **_: Author.objects.all(),
        permissions=(Unrestricted(),),
        presenter=SerializerPresenter(AuthorSerializer),
        metadata=metadata,
    )


def _target(metadata: Any = None) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Author.objects.get(pk=pk),
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
        permissions=(Unrestricted(),),
        metadata=metadata,
    )


def _views(metadata: Any) -> tuple[type, type, type, type, type]:
    """One view of each surface a spec is served on, every spec carrying ``metadata``."""

    class Viewset(ServiceViewSet):
        queryset = Author.objects.all()
        action_specs = {"create": _write(metadata)}

    class Reads(SelectorViewSet):
        queryset = Author.objects.all()
        action_specs = {"list": _read(metadata)}

    class Actions(GenericViewSet):
        queryset = Author.objects.all()

        @service_action(_write(metadata), detail=False, methods=["post"])
        def approve(self, request: Any) -> Any: ...

        @selector_action(_read(metadata), detail=False)
        def recent(self, request: Any) -> Any: ...

    return (
        type("Create", (ServiceCreateView,), {"spec": _write(metadata)}),
        type("Listing", (SelectorListView,), {"spec": _read(metadata)}),
        Viewset,
        Reads,
        Actions,
    )


def _patterns(prefix: str, metadata: Any) -> list[Any]:
    create, listing, viewset, reads, actions = _views(metadata)
    router = DefaultRouter()
    router.register(f"{prefix}/viewset", viewset, basename=f"{prefix}-viewset")
    router.register(f"{prefix}/reads", reads, basename=f"{prefix}-reads")
    router.register(f"{prefix}/actions", actions, basename=f"{prefix}-actions")
    return [
        path(f"{prefix}/create/", create.as_view()),
        path(f"{prefix}/list/", listing.as_view()),
        *router.urls,
    ]


# Each surface, as ``(route, method)`` under a prefix.
_SURFACES = [
    ("create/", "post"),
    ("list/", "get"),
    ("viewset/", "post"),
    ("reads/", "get"),
    ("actions/approve/", "post"),
    ("actions/recent/", "get"),
]


class _Everywhere(ServiceAutoSchema):
    """A project documenting the 422 on every spec, through the public method alone."""

    def documents_service_error(self, spec: Any) -> bool:
        return True


class _ApiSchema(ServiceAutoSchema):
    """myclub-member's ``ApiSchema``, less the 422 correction the default now is.

    It reached drfs' private ``resolve_service_spec`` to pop the 422 from every
    operation whose spec did not set ``document_service_error=True``. Here the
    subclass carries none of that: what it popped is not documented, and a
    spec keeping its 422 declares it in ``metadata``.
    """


urlpatterns = [
    *_patterns("undeclared", None),
    *_patterns("declared", _DECLARED),
    *_patterns("declined", {SERVICE_ERROR_METADATA_KEY: False}),
    path(
        "everywhere/",
        type(
            "Everywhere", (ServiceCreateView,), {"spec": _write(), "schema": _Everywhere()}
        ).as_view(),
    ),
    path(
        "everywhere-read/",
        type(
            "EverywhereRead", (SelectorListView,), {"spec": _read(), "schema": _Everywhere()}
        ).as_view(),
    ),
    path(
        "project/undeclared/",
        type(
            "ProjectUndeclared", (ServiceCreateView,), {"spec": _write(), "schema": _ApiSchema()}
        ).as_view(),
    ),
    path(
        "project/declared/",
        type(
            "ProjectDeclared",
            (ServiceCreateView,),
            {"spec": _write(_DECLARED), "schema": _ApiSchema()},
        ).as_view(),
    ),
    # Declared on the one view, with nothing on its spec.
    path(
        "extended/",
        extend_schema(responses={422: ServiceErrorSerializer})(
            type("Extended", (ServiceCreateView,), {"spec": _write()})
        ).as_view(),
    ),
    # The declaration is the served spec's: a target selector's is not read.
    path(
        "target/<int:pk>/",
        type(
            "Target",
            (ServiceUpdateView,),
            {
                "spec": ServiceSpec(
                    service=lambda **_: None,
                    permissions=(Unrestricted(),),
                    instance_selector_spec=_target(_DECLARED).derive(permissions=None),
                )
            },
        ).as_view(),
    ),
    path(
        "retrieve/<int:pk>/",
        type(
            "Retrieve",
            (SelectorRetrieveView,),
            {"spec": _target(_DECLARED), "serializer_class": AuthorSerializer},
        ).as_view(),
    ),
]


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)


def _responses(schema: dict[str, Any], route: str, method: str) -> dict[str, Any]:
    return schema["paths"][f"/{route}"][method]["responses"]


class TestTheDefault:
    @pytest.mark.parametrize(("route", "method"), _SURFACES)
    def test_a_spec_declaring_nothing_documents_no_422(
        self, schema: dict[str, Any], route: str, method: str
    ) -> None:
        assert "422" not in _responses(schema, f"undeclared/{route}", method)

    @pytest.mark.parametrize(("route", "method"), _SURFACES)
    def test_a_spec_declaring_false_documents_no_422(
        self, schema: dict[str, Any], route: str, method: str
    ) -> None:
        assert "422" not in _responses(schema, f"declined/{route}", method)


class TestADeclaredSpec:
    @pytest.mark.parametrize(("route", "method"), _SURFACES)
    def test_documents_the_422_on_every_surface_serving_it(
        self, schema: dict[str, Any], route: str, method: str
    ) -> None:
        response = _responses(schema, f"declared/{route}", method)["422"]
        assert response["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ServiceError"
        }

    def test_a_target_selector_s_declaration_is_not_the_operation_s(
        self, schema: dict[str, Any]
    ) -> None:
        assert "422" not in _responses(schema, "target/{id}/", "put")
        # The same selector, served as the operation, is documented with it.
        assert "422" in _responses(schema, "retrieve/{id}/", "get")


class TestAViewDeclaringIt:
    def test_extend_schema_documents_it_over_a_spec_declaring_nothing(
        self, schema: dict[str, Any]
    ) -> None:
        assert set(_responses(schema, "extended/", "post")) == {"201", "422"}


class TestAProjectSchema:
    @pytest.mark.parametrize("route", ["everywhere/", "everywhere-read/"])
    def test_overriding_the_public_method_documents_it_on_every_spec(
        self, schema: dict[str, Any], route: str
    ) -> None:
        method = "get" if route.endswith("read/") else "post"
        assert "422" in _responses(schema, route, method)

    def test_myclub_member_s_correction_needs_no_private_import(
        self, schema: dict[str, Any]
    ) -> None:
        assert set(_responses(schema, "project/undeclared/", "post")) == {"201"}
        assert set(_responses(schema, "project/declared/", "post")) == {"201", "422"}


class TestAMalformedDeclaration:
    @pytest.mark.parametrize("value", ["yes", 1, None])
    @pytest.mark.parametrize(
        ("base", "spec"), [(ServiceCreateView, _write), (SelectorListView, _read)]
    )
    def test_is_refused_naming_the_view(self, value: Any, base: type, spec: Any) -> None:
        view = type("Malformed", (base,), {"spec": spec({SERVICE_ERROR_METADATA_KEY: value})})
        generator = SchemaGenerator(patterns=[path("m/", view.as_view())])
        with pytest.raises(
            ImproperlyConfigured,
            match=r"Malformed's spec metadata\['document_service_error'\] must be True or False",
        ):
            generator.get_schema(request=None, public=True)
