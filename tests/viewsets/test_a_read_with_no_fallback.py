from __future__ import annotations

from typing import Any

import pytest
from django.urls import include, path
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter, SimpleRouter
from rest_framework.test import APIClient
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import SelectorViewSet, ServiceCreateMixin, ServiceViewSet, service_action
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.viewsets.selector_list_mixin import SelectorListMixin
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = [pytest.mark.django_db, pytest.mark.urls(__name__)]

_OPEN = (Unrestricted(),)
_PRESENTER = SerializerPresenter(AuthorSerializer)
_BY_PK = Parameters.of(Parameter("pk", "integer", required=True))


def _make_author() -> Author:
    return Author.objects.create(name="made")


def _list_authors() -> Any:
    return Author.objects.order_by("id")


def _get_author(*, pk: int) -> Author | None:
    return Author.objects.filter(pk=pk).first()


_CREATE = ServiceSpec(service=_make_author, permissions=_OPEN, presenter=_PRESENTER)
_LIST = SelectorSpec(
    kind=SelectorKind.LIST, selector=_list_authors, permissions=_OPEN, presenter=_PRESENTER
)
_RETRIEVE = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=_get_author,
    reads=_BY_PK,
    permissions=_OPEN,
    presenter=_PRESENTER,
)


class _CreateOnly(ServiceViewSet):
    action_specs = {"create": _CREATE}


class _CreateOnlyBehindAuth(ServiceViewSet):
    action_specs = {"create": _CREATE}
    permission_classes = [IsAuthenticated]


class _RowsNoSerializer(ServiceViewSet):
    action_specs = {"create": _CREATE}
    queryset = Author.objects.all()


class _SerializerNoRows(ServiceViewSet):
    action_specs = {"create": _CREATE}
    serializer_class = AuthorSerializer


class _RowsAndSerializer(ServiceViewSet):
    action_specs = {"create": _CREATE}
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer


class _OwnGetQueryset(ServiceViewSet):
    action_specs = {"create": _CREATE}
    serializer_class = AuthorSerializer

    def get_queryset(self) -> Any:
        return Author.objects.order_by("id")


class _OwnGetQuerysetNoSerializer(ServiceViewSet):
    """An own ``get_queryset`` answers for the rows and only the rows."""

    action_specs = {"create": _CREATE}

    def get_queryset(self) -> Any:  # pragma: no cover - the read is refused before it asks
        return Author.objects.order_by("id")


class _OwnGetSerializerClass(ServiceViewSet):
    action_specs = {"create": _CREATE}
    queryset = Author.objects.all()

    def get_serializer_class(self) -> Any:
        return AuthorSerializer


class _OwnGetSerializerClassNoRows(ServiceViewSet):
    """An own ``get_serializer_class`` answers for the serializer and only the serializer."""

    action_specs = {"create": _CREATE}

    def get_serializer_class(self) -> Any:  # pragma: no cover - the read is refused before it asks
        return AuthorSerializer


class _OwnGetSerializer(ServiceViewSet):
    """DRF's reads ask ``get_serializer()``, so an own one needs no ``serializer_class``."""

    action_specs = {"create": _CREATE}
    queryset = Author.objects.all()

    def get_serializer(self, *args: Any, **kwargs: Any) -> Any:
        return AuthorSerializer(*args, **kwargs)


class _OwnList(ServiceViewSet):
    action_specs = {"create": _CREATE}

    def list(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        return Response(["own"])


class _OwnRetrieve(ServiceViewSet):
    action_specs = {"create": _CREATE}

    def retrieve(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        return Response({"own": kwargs["pk"]})


class _OwnGetObject(ServiceViewSet):
    action_specs = {"create": _CREATE}
    serializer_class = AuthorSerializer

    def get_object(self) -> Author:
        return Author(pk=1, name="own")


class _OwnWritesNoSerializer(ServiceViewSet):
    """A project's own handlers, which DRF's metadata asks for a serializer to describe them."""

    action_specs = {"create": _CREATE}

    @action(detail=False, methods=["post"])
    def ping(self, request: Any) -> Any: ...

    def update(self, request: Any, *args: Any, **kwargs: Any) -> Any: ...


class _OwnWritesNoRows(ServiceViewSet):
    """DRF's metadata can describe the POST with this serializer, and asks ``get_object()``
    for the PUT, which has no rows to read."""

    action_specs = {"create": _CREATE}
    serializer_class = AuthorSerializer

    @action(detail=False, methods=["post"])
    def ping(self, request: Any) -> Any: ...

    def update(self, request: Any, *args: Any, **kwargs: Any) -> Any: ...


class _Rows:
    """A project's mixin below the package's own bases, which their ``super()`` calls reach."""

    def get_queryset(self) -> Any:
        return Author.objects.order_by("id")


class _RowsFromAMixinBelow(SelectorListMixin, _Rows, GenericViewSet):
    action_specs: dict[str, Any] = {}
    serializer_class = AuthorSerializer


class _CreateMixinAlone(ServiceCreateMixin, GenericViewSet):
    action_specs = {"create": _CREATE}


class _ListSpecAlone(ServiceViewSet):
    action_specs = {"list": _LIST}


class _SelectorRetrieveAlone(SelectorViewSet):
    action_specs = {"retrieve": _RETRIEVE}


class _SelectorListAlone(SelectorViewSet):
    action_specs = {"list": _LIST}


class _ServiceActionAlone(ServiceViewSet):
    action_specs: dict[str, Any] = {}

    @service_action(_CREATE, detail=False, methods=["post"])
    def make(self, request: Any) -> Any: ...


class _NoSpecs(ServiceViewSet):
    action_specs: dict[str, Any] = {}


_VIEWSETS: dict[str, type] = {
    "create-only": _CreateOnly,
    "behind-auth": _CreateOnlyBehindAuth,
    "rows-no-serializer": _RowsNoSerializer,
    "serializer-no-rows": _SerializerNoRows,
    "rows-and-serializer": _RowsAndSerializer,
    "own-get-queryset": _OwnGetQueryset,
    "own-get-queryset-no-serializer": _OwnGetQuerysetNoSerializer,
    "own-serializer-class": _OwnGetSerializerClass,
    "own-serializer-class-no-rows": _OwnGetSerializerClassNoRows,
    "own-get-serializer": _OwnGetSerializer,
    "own-list": _OwnList,
    "own-retrieve": _OwnRetrieve,
    "own-get-object": _OwnGetObject,
    "own-writes-no-serializer": _OwnWritesNoSerializer,
    "own-writes-no-rows": _OwnWritesNoRows,
    "rows-from-a-mixin-below": _RowsFromAMixinBelow,
    "create-mixin-alone": _CreateMixinAlone,
    "list-spec-alone": _ListSpecAlone,
    "selector-retrieve-alone": _SelectorRetrieveAlone,
    "selector-list-alone": _SelectorListAlone,
    "service-action-alone": _ServiceActionAlone,
    "no-specs": _NoSpecs,
}

_simple = SimpleRouter()
_default = DefaultRouter()
for _prefix, _viewset in _VIEWSETS.items():
    _simple.register(_prefix, _viewset, basename=f"simple-{_prefix}")
    _default.register(_prefix, _viewset, basename=f"default-{_prefix}")

urlpatterns = [
    path("simple/", include(_simple.urls)),
    path("default/", include(_default.urls)),
    path("mapped/get-post/", _CreateOnly.as_view({"get": "list", "post": "create"})),
    path("mapped/post/", _CreateOnly.as_view({"post": "create"})),
    path("mapped/put/<int:pk>/", _CreateOnly.as_view({"put": "update"})),
    path(
        "mapped/rows-in-as-view/",
        _CreateOnly.as_view(
            {"get": "list", "post": "create"},
            queryset=Author.objects.all(),
            serializer_class=AuthorSerializer,
        ),
    ),
]


@pytest.fixture
def _browsable(settings: Any) -> None:
    settings.TEMPLATES = [
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "APP_DIRS": True,
            "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
        }
    ]


def _client() -> APIClient:
    return APIClient(raise_request_exception=False)


def _allow(response: Any) -> set[str]:
    return set(response["Allow"].split(", "))


_ROUTERS = pytest.mark.parametrize("router", ["simple", "default"])


class TestACreateOnlyViewSet:
    @_ROUTERS
    @pytest.mark.parametrize("method", ["get", "head"])
    def test_a_read_of_the_list_route_is_a_405(self, router: str, method: str) -> None:
        response = getattr(_client(), method)(f"/{router}/create-only/")
        assert response.status_code == 405
        assert _allow(response) == {"POST", "OPTIONS"}

    @_ROUTERS
    @pytest.mark.parametrize("method", ["get", "head", "put", "patch", "delete"])
    def test_every_method_of_the_detail_route_is_a_405(self, router: str, method: str) -> None:
        response = getattr(_client(), method)(f"/{router}/create-only/1/")
        assert response.status_code == 405
        assert _allow(response) == {"OPTIONS"}

    @_ROUTERS
    def test_options_of_the_detail_route_answers(self, router: str) -> None:
        response = _client().options(f"/{router}/create-only/1/")
        assert response.status_code == 200
        assert _allow(response) == {"OPTIONS"}
        assert "actions" not in response.data

    @_ROUTERS
    def test_options_of_the_list_route_describes_the_create(self, router: str) -> None:
        response = _client().options(f"/{router}/create-only/")
        assert response.status_code == 200
        assert _allow(response) == {"POST", "OPTIONS"}

    @_ROUTERS
    def test_the_create_still_answers(self, router: str) -> None:
        assert _client().post(f"/{router}/create-only/").status_code == 201

    def test_a_format_suffix_is_the_same_route(self) -> None:
        assert _client().get("/default/create-only.json").status_code == 405

    @pytest.mark.usefixtures("_browsable")
    @pytest.mark.parametrize("route", ["create-only/", "create-only/1/"])
    def test_the_browsable_page_is_a_405(self, route: str) -> None:
        response = _client().get(f"/default/{route}", HTTP_ACCEPT="text/html")
        assert response.status_code == 405
        assert response["Content-Type"].startswith("text/html")

    def test_a_caller_the_view_refuses_is_refused_before_the_405(self) -> None:
        assert _client().get("/default/behind-auth/").status_code == 403

    def test_the_create_mixin_alone_mounts_no_detail_route(self) -> None:
        """The recipe's way to declare one with no detail route to answer at all."""
        listed = _client().get("/default/create-mixin-alone/")
        assert listed.status_code == 405
        assert _allow(listed) == {"POST", "OPTIONS"}
        assert _client().get("/default/create-mixin-alone/1/").status_code == 404


class TestItIsTheMappingThatDecides:
    def test_a_mapped_list_is_refused_with_no_router(self) -> None:
        response = _client().get("/mapped/get-post/")
        assert response.status_code == 405
        assert _allow(response) == {"POST", "OPTIONS"}

    def test_an_unmapped_get_stays_drf_s_own_answer(self) -> None:
        response = _client().get("/mapped/post/")
        assert response.status_code == 405
        assert _allow(response) == {"POST", "OPTIONS"}

    def test_options_of_a_write_alone_with_no_spec_answers(self) -> None:
        """No read is mapped, so only the viewset can open the gate."""
        response = _client().options("/mapped/put/1/")
        assert response.status_code == 200
        assert _allow(response) == {"OPTIONS"}

    def test_rows_handed_to_as_view_are_read(self) -> None:
        Author.objects.create(name="a")
        response = _client().get("/mapped/rows-in-as-view/")
        assert response.status_code == 200
        assert _allow(response) == {"GET", "HEAD", "POST", "OPTIONS"}


class TestEitherHalfMissing:
    @pytest.mark.parametrize(
        ("prefix", "missing"),
        [
            ("rows-no-serializer", "serializer"),
            ("serializer-no-rows", "rows"),
            ("own-get-queryset-no-serializer", "serializer"),
            ("own-serializer-class-no-rows", "rows"),
        ],
    )
    def test_the_read_is_refused(self, prefix: str, missing: str) -> None:
        for route, allowed in ((f"{prefix}/", {"POST", "OPTIONS"}), (f"{prefix}/1/", {"OPTIONS"})):
            response = _client().get(f"/default/{route}")
            assert response.status_code == 405, (route, missing)
            assert _allow(response) == allowed, (route, missing)

    @pytest.mark.parametrize("prefix", ["rows-no-serializer", "serializer-no-rows"])
    def test_options_of_the_detail_route_answers(self, prefix: str) -> None:
        response = _client().options(f"/default/{prefix}/1/")
        assert response.status_code == 200
        assert _allow(response) == {"OPTIONS"}


class TestTheOneSidedSpecs:
    @pytest.mark.parametrize(
        "route",
        ["list-spec-alone/1/", "selector-retrieve-alone/", "selector-list-alone/1/"],
    )
    def test_the_read_with_no_spec_is_refused(self, route: str) -> None:
        response = _client().get(f"/default/{route}")
        assert response.status_code == 405
        assert _allow(response) == {"OPTIONS"}

    def test_the_read_with_a_spec_answers(self) -> None:
        author = Author.objects.create(name="a")
        assert _client().get("/default/list-spec-alone/").status_code == 200
        assert _client().get("/default/selector-list-alone/").status_code == 200
        assert _client().get(f"/default/selector-retrieve-alone/{author.pk}/").status_code == 200

    def test_options_of_the_list_spec_s_detail_route_answers(self) -> None:
        response = _client().options("/default/list-spec-alone/1/")
        assert response.status_code == 200
        assert _allow(response) == {"OPTIONS"}

    def test_a_viewset_serving_only_a_custom_action_refuses_its_list(self) -> None:
        response = _client().get("/default/service-action-alone/")
        assert response.status_code == 405
        assert _allow(response) == {"OPTIONS"}

    def test_a_viewset_serving_nothing_refuses_its_list(self) -> None:
        response = _client().get("/default/no-specs/")
        assert response.status_code == 405
        assert _allow(response) == {"OPTIONS"}


class TestAFallbackThatCanRun:
    """A route that answered goes on answering, each by what makes its fallback possible."""

    @pytest.mark.parametrize(
        "prefix",
        [
            "rows-and-serializer",
            "own-get-queryset",
            "own-serializer-class",
            "own-get-serializer",
        ],
    )
    def test_both_routes_answer(self, prefix: str) -> None:
        author = Author.objects.create(name="a")
        listed = _client().get(f"/default/{prefix}/")
        assert listed.status_code == 200
        assert _allow(listed) == {"GET", "HEAD", "POST", "OPTIONS"}
        retrieved = _client().get(f"/default/{prefix}/{author.pk}/")
        assert retrieved.status_code == 200
        assert retrieved.data["name"] == "a"

    def test_rows_from_a_mixin_below_the_package_s_bases_answer(self) -> None:
        Author.objects.create(name="a")
        response = _client().get("/default/rows-from-a-mixin-below/")
        assert response.status_code == 200
        assert [row["name"] for row in response.data] == ["a"]


class TestAProjectsOwnHandler:
    def test_an_own_list_keeps_its_route(self) -> None:
        response = _client().get("/default/own-list/")
        assert response.status_code == 200
        assert response.data == ["own"]
        assert _allow(response) == {"GET", "HEAD", "POST", "OPTIONS"}

    def test_the_retrieve_beside_an_own_list_is_still_refused(self) -> None:
        assert _client().get("/default/own-list/1/").status_code == 405

    def test_an_own_retrieve_keeps_its_route(self) -> None:
        response = _client().get("/default/own-retrieve/1/")
        assert response.status_code == 200
        assert response.data == {"own": "1"}
        assert _allow(response) == {"GET", "HEAD", "OPTIONS"}

    def test_the_list_beside_an_own_retrieve_is_still_refused(self) -> None:
        assert _client().get("/default/own-retrieve/").status_code == 405

    def test_an_own_get_object_keeps_the_retrieve(self) -> None:
        response = _client().get("/default/own-get-object/1/")
        assert response.status_code == 200
        assert response.data["name"] == "own"

    def test_an_own_get_object_says_nothing_of_the_list(self) -> None:
        assert _client().get("/default/own-get-object/").status_code == 405


class TestOptionsOfAProjectsOwnWrite:
    """A handler of the project's stays in ``Allow``, and DRF's metadata, asked to describe it,
    asserts on what the viewset lacks. OPTIONS answers and leaves that method undescribed."""

    @pytest.mark.parametrize(
        ("route", "allowed"),
        [
            ("own-writes-no-serializer/ping/", {"POST", "OPTIONS"}),
            ("own-writes-no-serializer/1/", {"PUT", "OPTIONS"}),
            ("own-writes-no-rows/1/", {"PUT", "OPTIONS"}),
        ],
    )
    def test_it_answers_where_drf_s_metadata_cannot_describe_it(
        self, route: str, allowed: set[str]
    ) -> None:
        response = _client().options(f"/default/{route}")
        assert response.status_code == 200
        assert _allow(response) == allowed
        assert "actions" not in response.data

    def test_it_is_described_where_drf_s_metadata_can(self) -> None:
        response = _client().options("/default/own-writes-no-rows/ping/")
        assert response.status_code == 200
        assert _allow(response) == {"POST", "OPTIONS"}
        assert "name" in response.data["actions"]["POST"]
