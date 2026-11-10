from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.urls import path, re_path
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.settings import spectacular_settings
from rest_framework import serializers
from rest_framework.routers import SimpleRouter
from rest_framework.settings import api_settings

from django_spec_rest import (
    SelectorListView,
    SelectorRetrieveView,
    SelectorViewSet,
    ServiceCreateView,
    ServiceViewSet,
    selector_action,
    service_action,
)
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

_OPEN = (Unrestricted(),)
_PRESENTER = SerializerPresenter(AuthorSerializer)
_BY_PK = Parameters.of(Parameter("pk", "integer", required=True, help="The author's id."))


class _NameIn(serializers.Serializer):
    name = serializers.CharField()


def _rows() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda: Author.objects.all(),
        permissions=_OPEN,
        presenter=_PRESENTER,
    )


def _row() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
        reads=_BY_PK,
        permissions=_OPEN,
        presenter=_PRESENTER,
    )


_RENAME = ServiceSpec(
    service=lambda *, instance, data: instance,
    permissions=_OPEN,
    validator=SerializerValidator(_NameIn),
    presenter=_PRESENTER,
    instance_selector_spec=SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
        reads=_BY_PK,
    ),
)


class _NoQueryset(ServiceViewSet):
    """The quickstart's shape: specs for every action, and no ``queryset``."""

    action_specs = {
        "list": _rows(),
        "retrieve": _row(),
        "partial_update": _RENAME,
        "update": _RENAME,
        "destroy": _RENAME,
    }

    @selector_action(_row())
    def card(self, request: Any, pk: Any = None) -> None:
        """Stubbed."""

    @service_action(_RENAME, detail=True, methods=["post"])
    def rename(self, request: Any, pk: Any = None) -> None:
        """Stubbed."""


class _ByHex(SelectorViewSet):
    """No ``queryset``, and a lookup regex that types the capture itself."""

    lookup_value_regex = "[0-9a-f]+"
    action_specs = {"list": _rows(), "retrieve": _row()}


class _WithQueryset(SelectorViewSet):
    queryset = Author.objects.all()
    action_specs = {"list": _rows(), "retrieve": _row()}


# A retrieve whose spec reads no ``slug``: nothing declares the capture's type.
# A standalone view, since a router-mounted one is refused at ``as_view()``.
_Undeclared = type(
    "_Undeclared",
    (SelectorRetrieveView,),
    {
        "spec": SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda: Author.objects.first(),
            permissions=_OPEN,
            presenter=_PRESENTER,
        )
    },
)


def _books_of_author() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda *, author_id: Author.objects.filter(pk=author_id),
        reads=Parameters.of(Parameter("author_id", "integer", required=True)),
        permissions=_OPEN,
        presenter=_PRESENTER,
    )


class _RankIn(serializers.Serializer):
    rank = serializers.IntegerField()


def _shelved() -> ServiceSpec:
    """A create whose service reads the route's ``shelf`` itself."""
    return ServiceSpec(
        service=lambda *, shelf, data: Author.objects.first(),
        reads=Parameters.of(Parameter("shelf", "integer", required=True)),
        permissions=_OPEN,
        validator=SerializerValidator(_RankIn),
        presenter=_PRESENTER,
    )


# Two captures, one ``pk`` and one a ``_pk`` suffix, each its own read.
_Parented = type(
    "_Parented",
    (SelectorRetrieveView,),
    {
        "spec": SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, parent_pk, pk: Author.objects.filter(pk=pk).first(),
            reads=Parameters.of(
                Parameter("parent_pk", "string", required=True, help="The parent."),
                Parameter("pk", "integer", required=True, help="The child."),
            ),
            permissions=_OPEN,
            presenter=_PRESENTER,
        )
    },
)


_router = SimpleRouter()
_router.register("bare", _NoQueryset, basename="bare")
_router.register("hex", _ByHex, basename="hex")
_router.register("model", _WithQueryset, basename="model")

urlpatterns = [
    *_router.urls,
    re_path(r"^undeclared/(?P<slug>[^/.]+)/$", _Undeclared.as_view()),
    re_path(
        r"^nested/(?P<author_id>[^/.]+)/$",
        type("_Nested", (SelectorListView,), {"spec": _books_of_author()}).as_view(),
    ),
    re_path(r"^parents/(?P<parent_pk>[^/.]+)/(?P<pk>[^/.]+)/$", _Parented.as_view()),
    path(
        "slugged/<slug:pk>/", type("_Slugged", (SelectorRetrieveView,), {"spec": _row()}).as_view()
    ),
    re_path(
        r"^shelves/(?P<shelf>[^/.]+)/(?P<rank>[^/.]+)/$",
        type("_Shelved", (ServiceCreateView,), {"spec": _shelved()}).as_view(),
    ),
]


@pytest.fixture(scope="module", autouse=True)
def _enable_openapi() -> None:
    enable_openapi()


@pytest.fixture
def warnings(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Each warning drf-spectacular emits, prefixed with the class it was inspecting."""
    emitted: list[str] = []

    def emit(msg: str, severity: str) -> None:
        traces = GENERATOR_STATS._traces
        emitted.append(f"{traces[-1][2] if traces else ''}: {msg}")

    monkeypatch.setattr(GENERATOR_STATS, "emit", emit)
    yield emitted


@pytest.fixture
def schema(warnings: list[str]) -> dict[str, Any]:
    return SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)


def _path_parameter(schema: dict[str, Any], route: str, method: str, name: str) -> dict[str, Any]:
    (parameter,) = [
        p
        for p in schema["paths"][route][method].get("parameters", [])
        if p["in"] == "path" and p["name"] == name
    ]
    return parameter


@pytest.mark.parametrize(
    ("route", "method"),
    [
        ("/bare/{id}/", "get"),
        ("/bare/{id}/", "patch"),
        ("/bare/{id}/", "put"),
        ("/bare/{id}/", "delete"),
        ("/bare/{id}/card/", "get"),
        ("/bare/{id}/rename/", "post"),
    ],
)
def test_a_viewset_with_no_queryset_types_its_lookup_from_the_spec(
    schema: dict[str, Any], route: str, method: str
) -> None:
    parameter = _path_parameter(schema, route, method, "id")
    assert parameter["schema"] == {"type": "integer"}
    assert parameter["description"] == "The author's id."
    assert parameter["required"] is True


def test_a_viewset_with_no_queryset_does_not_warn_of_its_lookup(
    schema: dict[str, Any], warnings: list[str]
) -> None:
    assert not [w for w in warnings if w.startswith("_NoQueryset:")]


def test_a_route_capture_a_list_spec_reads_is_typed_from_it(schema: dict[str, Any]) -> None:
    parameter = _path_parameter(schema, "/nested/{author_id}/", "get", "author_id")
    assert parameter["schema"] == {"type": "integer"}


def test_a_model_s_answer_stands(schema: dict[str, Any]) -> None:
    """With a ``queryset`` drf-spectacular reads the model's primary key, as it always did."""
    parameter = _path_parameter(schema, "/model/{id}/", "get", "id")
    assert parameter["schema"] == {"type": "integer"}
    assert parameter["description"] == "A unique integer value identifying this author."


def test_a_capture_no_spec_declares_is_left_to_drf_spectacular(
    schema: dict[str, Any], warnings: list[str]
) -> None:
    parameter = _path_parameter(schema, "/undeclared/{slug}/", "get", "slug")
    assert parameter["schema"] == {"type": "string"}
    assert [w for w in warnings if w.startswith("_Undeclared:") and 'parameter "slug"' in w]


def test_a_lookup_regex_types_the_capture_itself(schema: dict[str, Any]) -> None:
    """The viewset's ``lookup_value_regex`` is the route's own type."""
    parameter = _path_parameter(schema, "/hex/{id}/", "get", "id")
    assert parameter["schema"] == {"type": "string", "pattern": "^[0-9a-f]+$"}


def test_a_path_converter_types_the_capture_itself(schema: dict[str, Any]) -> None:
    """A ``path()`` converter is the route's own type."""
    parameter = _path_parameter(schema, "/slugged/{id}/", "get", "id")
    assert parameter["schema"] == {"type": "string"}
    assert "description" not in parameter


def test_a_service_spec_s_own_read_types_the_capture(schema: dict[str, Any]) -> None:
    parameter = _path_parameter(schema, "/shelves/{shelf}/{rank}/", "post", "shelf")
    assert parameter["schema"] == {"type": "integer"}


def test_a_validator_s_field_never_types_the_capture(
    schema: dict[str, Any], warnings: list[str]
) -> None:
    """The Validator's integer ``rank`` is the request body's."""
    parameter = _path_parameter(schema, "/shelves/{shelf}/{rank}/", "post", "rank")
    assert parameter["schema"] == {"type": "string"}
    assert [w for w in warnings if w.startswith("_Shelved:") and 'parameter "rank"' in w]


def _two_captures(schema: dict[str, Any], route: str, parent: str) -> list[tuple[Any, ...]]:
    return [
        (name, p["schema"], p["description"])
        for name in (parent, "id")
        for p in [_path_parameter(schema, route, "get", name)]
    ]


def test_each_capture_is_typed_from_its_own_read(schema: dict[str, Any]) -> None:
    assert _two_captures(schema, "/parents/{parent_pk}/{id}/", "parent_pk") == [
        ("parent_pk", {"type": "string"}, "The parent."),
        ("id", {"type": "integer"}, "The child."),
    ]


def test_a_suffixed_capture_is_typed_from_its_own_read(
    monkeypatch: pytest.MonkeyPatch, warnings: list[str]
) -> None:
    """Under ``SCHEMA_COERCE_PATH_PK_SUFFIX``, ``parent_pk`` is documented as ``parent_id``."""
    monkeypatch.setattr(spectacular_settings, "SCHEMA_COERCE_PATH_PK_SUFFIX", True)
    schema = SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)
    assert _two_captures(schema, "/parents/{parent_id}/{id}/", "parent_id") == [
        ("parent_id", {"type": "string"}, "The parent."),
        ("id", {"type": "integer"}, "The child."),
    ]
    assert not [w for w in warnings if w.startswith("_Parented:")]
    shelf = _path_parameter(schema, "/shelves/{shelf}/{rank}/", "post", "shelf")
    assert shelf["schema"] == {"type": "integer"}


def test_an_uncoerced_pk_is_typed_from_its_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """With DRF's ``SCHEMA_COERCE_PATH_PK`` off the router's ``{pk}`` is documented as itself."""
    monkeypatch.setattr(api_settings, "SCHEMA_COERCE_PATH_PK", False)
    schema = SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)
    parameter = _path_parameter(schema, "/bare/{pk}/", "get", "pk")
    assert parameter["schema"] == {"type": "integer"}
    assert parameter["description"] == "The author's id."
