"""``ServiceAutoSchema`` documenting kernel specs, end to end through drf-spectacular.

Every view here carries the kernel's own ``ServiceSpec`` or ``SelectorSpec``,
with no ``serializer_class``: the request body is read off the spec's
Validator and the response off its presenter, so each test fails against a
schema that reads only drfs specs, which falls back to the view's missing
``serializer_class`` and documents no body at all.

- **A ``SerializerValidator``** is documented by its serializer, under the
  component name drf-spectacular gives that class; **any other Validator** by
  the kernel's ``parameters_schema`` over the parameters the body carries,
  under the edge's unknown-argument policy.
- **A ``SerializerPresenter``** is documented by its serializer; **any other
  presenter** by the kernel's ``output_schema``. A spec presenting rows is an
  array of them.
- **The status** is the view's ``success_status`` over the action's default,
  as the kernel route answers.
- **A FilterSet's query parameters** are the kernel's ``filter_set_parameters``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

import django_filters
import pytest
from django.urls import path
from django_service_specs import (
    DataclassPresenter,
    DataclassValidator,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
    Validator,
)
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.routers import DefaultRouter
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import (
    SelectorListView,
    SelectorRetrieveView,
    ServiceCreateView,
    ServiceDeleteView,
    ServiceUpdateView,
    ServiceViewSet,
    selector_action,
    service_action,
)
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author, Post
from tests.testapp.serializers import AuthorSerializer, PostSerializer

_OPEN = (Unrestricted(),)
_BY_PK = Parameters.of(Parameter("pk", "integer", required=True))
_PRESENTER = SerializerPresenter(AuthorSerializer)


class NameInSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=20)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField()


@dataclass
class _NameRow:
    name: str


@dataclass
class _Named:
    id: int
    name: str


class _NameValidator(Validator):
    """A Validator that is no serializer and takes a partial call."""

    def parameters(self) -> Parameters:
        return Parameters.of(Parameter("name", "string", required=True))

    def validate(self, arguments: Any, context: Any) -> dict[str, Any]:
        return dict(arguments)


class _Owned(TypedDict):
    owner: str


def _owner() -> _Owned:
    return {"owner": "me"}


def _list_authors() -> Any:
    return Author.objects.order_by("id")


def _get_author(*, pk: int) -> Author | None:
    return Author.objects.filter(pk=pk).first()


def _create_author(*, data: Any) -> Any: ...


def _create_owned(*, data: Any, tenant: str, owner: str) -> Any: ...


def _rename(*, instance: Author, data: Any) -> Any: ...


def _delete(*, instance: Author) -> None: ...


def _target() -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.RETRIEVE, selector=_get_author, reads=_BY_PK)


def _create(**fields: Any) -> ServiceSpec:
    defaults: dict[str, Any] = {
        "service": _create_author,
        "permissions": _OPEN,
        "validator": SerializerValidator(NameInSerializer),
        "presenter": _PRESENTER,
    }
    return ServiceSpec(**{**defaults, **fields})


def _update(**fields: Any) -> ServiceSpec:
    defaults: dict[str, Any] = {
        "service": _rename,
        "permissions": _OPEN,
        "validator": SerializerValidator(NameInSerializer),
        "presenter": _PRESENTER,
        "instance_selector_spec": _target(),
    }
    return ServiceSpec(**{**defaults, **fields})


def _destroy(**fields: Any) -> ServiceSpec:
    defaults: dict[str, Any] = {
        "service": _delete,
        "permissions": _OPEN,
        "instance_selector_spec": _target(),
    }
    return ServiceSpec(**{**defaults, **fields})


def _list(**fields: Any) -> SelectorSpec:
    defaults: dict[str, Any] = {
        "selector": _list_authors,
        "permissions": _OPEN,
        "presenter": _PRESENTER,
    }
    return SelectorSpec(kind=SelectorKind.LIST, **{**defaults, **fields})


def _retrieve(**fields: Any) -> SelectorSpec:
    defaults: dict[str, Any] = {
        "selector": _get_author,
        "reads": _BY_PK,
        "permissions": _OPEN,
        "presenter": _PRESENTER,
    }
    return SelectorSpec(kind=SelectorKind.RETRIEVE, **{**defaults, **fields})


def _view(base: type, spec: Any, **attrs: Any) -> Any:
    return type("_View", (base,), {"queryset": Author.objects.all(), "spec": spec, **attrs})


def _status_from_result(*, result: Any) -> int:
    return 202


class _PostFilter(django_filters.FilterSet):
    title = django_filters.CharFilter(lookup_expr="icontains")
    published = django_filters.BooleanFilter()
    kind = django_filters.ChoiceFilter(field_name="body", choices=[("a", "A"), ("b", "B")])
    pks = django_filters.BaseInFilter(field_name="id")

    class Meta:
        model = Post
        fields: list[str] = []


def _list_posts() -> Any:
    return Post.objects.order_by("id")


def _get_post(*, pk: int) -> Post | None:
    return Post.objects.filter(pk=pk).first()


_POSTS = SerializerPresenter(PostSerializer)


class _AnnotatedUpdateView(ServiceUpdateView):
    queryset = Author.objects.all()
    spec = _update()

    @extend_schema(request=ReasonSerializer)
    def patch(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        return super().patch(request, *args, **kwargs)


class _AuthorViewSet(ServiceViewSet):
    queryset = Author.objects.all()
    action_specs = {
        "list": _list(),
        "retrieve": _retrieve(),
        "create": _create(),
        "update": _update(),
        "destroy": _destroy(),
    }


class _ActionViewSet(GenericViewSet):
    queryset = Author.objects.all()

    @service_action(_create(), detail=False, methods=["post"])
    def approve(self, request: Any) -> Any: ...

    @selector_action(_list(), detail=False)
    def recent(self, request: Any) -> Any: ...

    @selector_action(_list(presenter=DataclassPresenter(_Named)), detail=False)
    def named(self, request: Any) -> Any: ...


_router = DefaultRouter()
_router.register("authors", _AuthorViewSet, basename="authors")
_router.register("actions", _ActionViewSet, basename="actions")

urlpatterns = [
    path("create/", _view(ServiceCreateView, _create()).as_view()),
    path("create-202/", _view(ServiceCreateView, _create(), success_status=202).as_view()),
    path(
        "create-callable/",
        _view(ServiceCreateView, _create(), success_status=_status_from_result).as_view(),
    ),
    path("create-may-be-none/", _view(ServiceCreateView, _create(allow_none=True)).as_view()),
    path(
        "create-bare/",
        _view(ServiceCreateView, _create(presenter=None, allow_none=True)).as_view(),
    ),
    path(
        "create-dataclass-out/",
        _view(ServiceCreateView, _create(presenter=DataclassPresenter(_Named))).as_view(),
    ),
    path("create-many/", _view(ServiceCreateView, _create(many=True)).as_view()),
    path("create-returns-many/", _view(ServiceCreateView, _create(returns_many=True)).as_view()),
    path(
        "create-re-read-list/",
        _view(
            ServiceCreateView,
            _create(
                presenter=None,
                output_selector_spec=SelectorSpec(
                    kind=SelectorKind.LIST, selector=_list_authors, presenter=_PRESENTER
                ),
            ),
        ).as_view(),
    ),
    path(
        "create-many-dataclass/",
        _view(
            ServiceCreateView,
            _create(
                many=True,
                validator=DataclassValidator(_NameRow),
                presenter=DataclassPresenter(_Named),
            ),
        ).as_view(),
    ),
    path("create-no-input/", _view(ServiceCreateView, _create(validator=None)).as_view()),
    path(
        "t/<slug:tenant>/owned/",
        _view(
            ServiceCreateView,
            _create(
                service=_create_owned,
                validator=DataclassValidator(_NameRow),
                reads=Parameters.of(
                    Parameter("tenant", "string", required=True),
                    Parameter("owner", "string", required=True),
                ),
                kwargs=_owner,
            ),
        ).as_view(),
    ),
    path("update/<int:pk>/", _view(ServiceUpdateView, _update()).as_view()),
    path(
        "update-whole/<int:pk>/",
        _view(ServiceUpdateView, _update(validator=SerializerValidator(_NameRow))).as_view(),
    ),
    path("update-annotated/<int:pk>/", _AnnotatedUpdateView.as_view()),
    path("update-partial/<int:pk>/", _view(ServiceUpdateView, _update(partial=True)).as_view()),
    path(
        "update-own/<int:author>/",
        _view(ServiceUpdateView, _update(validator=_NameValidator())).as_view(),
    ),
    path("delete/<int:pk>/", _view(ServiceDeleteView, _destroy()).as_view()),
    path(
        "delete-with-reason/<int:pk>/",
        _view(
            ServiceDeleteView, _destroy(validator=SerializerValidator(ReasonSerializer))
        ).as_view(),
    ),
    path(
        "delete-own-reason/<int:pk>/",
        _view(ServiceDeleteView, _destroy(validator=_NameValidator())).as_view(),
    ),
    path("archive/<int:pk>/", _view(ServiceDeleteView, _destroy(presenter=_PRESENTER)).as_view()),
    path("authors-list/", _view(SelectorListView, _list()).as_view()),
    path(
        "authors-list-dataclass/",
        _view(SelectorListView, _list(presenter=DataclassPresenter(_Named))).as_view(),
    ),
    path(
        "authors-list-bare/",
        _view(SelectorListView, _list(presenter=None), serializer_class=AuthorSerializer).as_view(),
    ),
    path(
        "authors-paged/",
        _view(SelectorListView, _list(), pagination_class=PageNumberPagination).as_view(),
    ),
    path(
        "authors-paged-dataclass/",
        _view(
            SelectorListView,
            _list(presenter=DataclassPresenter(_Named)),
            pagination_class=PageNumberPagination,
        ).as_view(),
    ),
    path("author/<int:pk>/", _view(SelectorRetrieveView, _retrieve()).as_view()),
    path(
        "author-dataclass/<int:pk>/",
        _view(SelectorRetrieveView, _retrieve(presenter=DataclassPresenter(_Named))).as_view(),
    ),
    path(
        "posts/",
        _view(
            SelectorListView,
            SelectorSpec(
                kind=SelectorKind.LIST,
                selector=_list_posts,
                permissions=_OPEN,
                presenter=_POSTS,
                filter_set=_PostFilter,
            ),
            queryset=Post.objects.all(),
        ).as_view(),
    ),
    path(
        "post/<int:pk>/",
        _view(
            SelectorRetrieveView,
            SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=_get_post,
                reads=_BY_PK,
                permissions=_OPEN,
                presenter=_POSTS,
                filter_set=_PostFilter,
            ),
            queryset=Post.objects.all(),
        ).as_view(),
    ),
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


def _response(schema: dict[str, Any], route: str, method: str, status: str) -> dict[str, Any]:
    return _op(schema, route, method)["responses"][status]["content"]["application/json"]["schema"]


def _component(schema: dict[str, Any], ref: str) -> dict[str, Any]:
    return schema["components"]["schemas"][ref.rsplit("/", 1)[1]]


class TestTheRequestBody:
    def test_a_serializer_validator_is_documented_by_its_serializer(
        self, schema: dict[str, Any]
    ) -> None:
        # The component is drf-spectacular's name for the author's serializer,
        # which a generated client keys on.
        assert _body(schema, "/create/", "post") == {"$ref": "#/components/schemas/NameIn"}
        assert schema["components"]["schemas"]["NameIn"]["required"] == ["name"]

    def test_a_patch_is_documented_partial(self, schema: dict[str, Any]) -> None:
        body = _body(schema, "/update/{id}/", "patch")
        assert body == {"$ref": "#/components/schemas/PatchedNameIn"}
        assert "required" not in _component(schema, body["$ref"])

    def test_a_put_is_documented_whole(self, schema: dict[str, Any]) -> None:
        assert _body(schema, "/update/{id}/", "put") == {"$ref": "#/components/schemas/NameIn"}

    def test_a_patch_a_dataclass_validates_whole_is_documented_whole(
        self, schema: dict[str, Any]
    ) -> None:
        # A dataclass builds its instance from every field, so the kernel route
        # validates a PATCH whole, and the schema says so.
        body = _body(schema, "/update-whole/{id}/", "patch")
        assert "Patched" not in body["$ref"]
        assert _component(schema, body["$ref"])["required"] == ["name"]

    def test_an_extend_schema_request_is_documented_partial_on_a_patch(
        self, schema: dict[str, Any]
    ) -> None:
        # The author's annotation wins, and drf-spectacular documents it under
        # a PATCH as it does on any view.
        assert _body(schema, "/update-annotated/{id}/", "patch") == {
            "$ref": "#/components/schemas/PatchedReason"
        }

    def test_a_partial_spec_documents_its_put_partial(self, schema: dict[str, Any]) -> None:
        assert _body(schema, "/update-partial/{id}/", "put") == {
            "$ref": "#/components/schemas/PatchedNameIn"
        }

    def test_a_many_spec_takes_an_array_of_rows(self, schema: dict[str, Any]) -> None:
        assert _body(schema, "/create-many/", "post") == {
            "type": "array",
            "items": {"$ref": "#/components/schemas/NameIn"},
        }

    def test_a_many_spec_over_another_validator_takes_an_array_of_its_rows(
        self, schema: dict[str, Any]
    ) -> None:
        body = _body(schema, "/create-many-dataclass/", "post")
        assert body["type"] == "array"
        assert set(body["items"]["properties"]) == {"name"}

    def test_another_validator_is_its_parameters_schema(self, schema: dict[str, Any]) -> None:
        body = _body(schema, "/update-own/{author}/", "put")
        assert body["type"] == "object"
        assert body["properties"] == {"name": {"type": "string"}}
        assert body["required"] == ["name"]
        # The edge drops an undeclared key, so the body is not closed.
        assert "additionalProperties" not in body

    def test_another_validator_s_patch_requires_nothing(self, schema: dict[str, Any]) -> None:
        body = _body(schema, "/update-own/{author}/", "patch")
        assert body["properties"] == {"name": {"type": "string"}}
        assert "required" not in body

    def test_the_target_s_reads_are_no_body_key(self, schema: dict[str, Any]) -> None:
        # ``pk`` is the target lookup's read and no route capture here: the
        # body still does not choose the row.
        assert set(_body(schema, "/update-own/{author}/", "put")["properties"]) == {"name"}

    def test_a_route_capture_and_a_provider_s_key_are_no_body_key(
        self, schema: dict[str, Any]
    ) -> None:
        # ``tenant`` is captured by the route and ``owner`` filled by the
        # ``kwargs`` provider, so the client is asked for neither.
        body = _body(schema, "/t/{tenant}/owned/", "post")
        assert set(body["properties"]) == {"name"}

    def test_a_delete_with_a_validator_documents_its_body(self, schema: dict[str, Any]) -> None:
        assert _body(schema, "/delete-with-reason/{id}/", "delete") == {
            "$ref": "#/components/schemas/Reason"
        }
        assert set(_body(schema, "/delete-own-reason/{id}/", "delete")["properties"]) == {"name"}

    def test_a_spec_taking_nothing_documents_no_body(self, schema: dict[str, Any]) -> None:
        assert "requestBody" not in _op(schema, "/delete/{id}/", "delete")
        assert "requestBody" not in _op(schema, "/create-no-input/", "post")


class TestTheResponse:
    def test_a_create_answers_201_with_its_presenter_s_serializer(
        self, schema: dict[str, Any]
    ) -> None:
        assert _response(schema, "/create/", "post", "201") == {
            "$ref": "#/components/schemas/Author"
        }
        assert set(_op(schema, "/create/", "post")["responses"]) == {"201", "422"}

    def test_the_view_s_status_is_documented(self, schema: dict[str, Any]) -> None:
        assert set(_op(schema, "/create-202/", "post")["responses"]) == {"202", "422"}

    def test_a_callable_status_documents_the_action_s_default(self, schema: dict[str, Any]) -> None:
        assert set(_op(schema, "/create-callable/", "post")["responses"]) == {"201", "422"}

    def test_a_spec_that_may_present_nothing_documents_its_204(
        self, schema: dict[str, Any]
    ) -> None:
        responses = _op(schema, "/create-may-be-none/", "post")["responses"]
        assert set(responses) == {"201", "204", "422"}
        assert "content" not in responses["204"]

    def test_no_presenter_documents_no_content_at_the_status(self, schema: dict[str, Any]) -> None:
        # The spec may present nothing, and the no-content response is already
        # the one documented, at its status: no 204 beside it.
        responses = _op(schema, "/create-bare/", "post")["responses"]
        assert set(responses) == {"201", "422"}
        assert "content" not in responses["201"]

    def test_another_presenter_is_its_output_schema(self, schema: dict[str, Any]) -> None:
        body = _response(schema, "/create-dataclass-out/", "post", "201")
        assert body["type"] == "object"
        assert set(body["properties"]) == {"id", "name"}

    def test_a_many_spec_presents_an_array(self, schema: dict[str, Any]) -> None:
        assert _response(schema, "/create-many/", "post", "201") == {
            "type": "array",
            "items": {"$ref": "#/components/schemas/Author"},
        }
        body = _response(schema, "/create-many-dataclass/", "post", "201")
        assert body["type"] == "array"
        assert set(body["items"]["properties"]) == {"id", "name"}

    def test_a_returns_many_spec_presents_an_array(self, schema: dict[str, Any]) -> None:
        assert _response(schema, "/create-returns-many/", "post", "201") == {
            "type": "array",
            "items": {"$ref": "#/components/schemas/Author"},
        }

    def test_a_list_re_read_presents_an_array(self, schema: dict[str, Any]) -> None:
        # The output selector's presenter renders its rows, and a LIST re-read
        # never presents nothing, so no 204 is documented beside them.
        responses = _op(schema, "/create-re-read-list/", "post")["responses"]
        assert set(responses) == {"201", "422"}
        assert _response(schema, "/create-re-read-list/", "post", "201") == {
            "type": "array",
            "items": {"$ref": "#/components/schemas/Author"},
        }

    def test_a_destroy_presenting_a_row_answers_200(self, schema: dict[str, Any]) -> None:
        assert _response(schema, "/archive/{id}/", "delete", "200") == {
            "$ref": "#/components/schemas/Author"
        }

    def test_a_destroy_presenting_nothing_answers_204(self, schema: dict[str, Any]) -> None:
        assert set(_op(schema, "/delete/{id}/", "delete")["responses"]) == {"204"}

    def test_a_service_error_is_documented_where_there_is_a_validator(
        self, schema: dict[str, Any]
    ) -> None:
        # The ``ServiceError`` component carries under its name.
        assert _response(schema, "/create/", "post", "422") == {
            "$ref": "#/components/schemas/ServiceError"
        }
        assert "422" not in _op(schema, "/create-no-input/", "post")["responses"]


class TestTheReadSide:
    def test_a_list_is_an_array_of_its_presenter_s_serializer(self, schema: dict[str, Any]) -> None:
        assert _response(schema, "/authors-list/", "get", "200") == {
            "type": "array",
            "items": {"$ref": "#/components/schemas/Author"},
        }

    def test_a_retrieve_is_its_presenter_s_serializer(self, schema: dict[str, Any]) -> None:
        assert _response(schema, "/author/{id}/", "get", "200") == {
            "$ref": "#/components/schemas/Author"
        }

    def test_another_presenter_is_its_output_schema(self, schema: dict[str, Any]) -> None:
        listed = _response(schema, "/authors-list-dataclass/", "get", "200")
        assert listed["type"] == "array"
        assert set(listed["items"]["properties"]) == {"id", "name"}
        one = _response(schema, "/author-dataclass/{id}/", "get", "200")
        assert set(one["properties"]) == {"id", "name"}

    def test_no_presenter_is_the_view_s_serializer_class(self, schema: dict[str, Any]) -> None:
        assert _response(schema, "/authors-list-bare/", "get", "200") == {
            "type": "array",
            "items": {"$ref": "#/components/schemas/Author"},
        }

    def test_a_filter_set_s_parameters_are_the_kernel_s(self, schema: dict[str, Any]) -> None:
        parameters = {p["name"]: p for p in _op(schema, "/posts/", "get")["parameters"]}
        assert set(parameters) == {"title", "published", "kind", "pks"}
        assert all(p["in"] == "query" and "required" not in p for p in parameters.values())
        assert parameters["published"]["schema"] == {"type": "boolean"}
        assert parameters["kind"]["schema"]["enum"] == ["a", "b"]
        assert parameters["pks"]["schema"]["type"] == "array"

    def test_a_paged_list_is_the_paginator_s_envelope(self, schema: dict[str, Any]) -> None:
        # Once, whichever the presenter: a serializer's rows under the paged
        # component drf-spectacular names, a raw row inside the envelope.
        assert _response(schema, "/authors-paged/", "get", "200") == {
            "$ref": "#/components/schemas/PaginatedAuthorList"
        }
        envelope = schema["components"]["schemas"]["PaginatedAuthorList"]
        assert envelope["properties"]["results"] == {
            "type": "array",
            "items": {"$ref": "#/components/schemas/Author"},
        }
        raw = _response(schema, "/authors-paged-dataclass/", "get", "200")
        assert raw["properties"]["results"]["type"] == "array"
        assert set(raw["properties"]["results"]["items"]["properties"]) == {"id", "name"}

    @pytest.mark.django_db
    def test_an_array_filter_is_read_from_a_repeated_key(self) -> None:
        # The documented style is OpenAPI's default for an array, one key per
        # value, which the route reads as it reads a comma list.
        author = Author.objects.create(name="a")
        posts = [Post.objects.create(title=str(i), author=author) for i in range(3)]
        view = urlpatterns[[str(u.pattern) for u in urlpatterns].index("posts/")].callback
        request = APIRequestFactory().get(f"/posts/?pks={posts[0].pk}&pks={posts[2].pk}")
        response = view(request)
        assert response.status_code == 200
        assert [row["id"] for row in response.data] == [posts[0].pk, posts[2].pk]

    def test_a_retrieve_documents_no_filter_parameters(self, schema: dict[str, Any]) -> None:
        names = {p["name"] for p in _op(schema, "/post/{id}/", "get")["parameters"]}
        assert names == {"id"}


class TestViewsets:
    def test_action_specs_are_documented(self, schema: dict[str, Any]) -> None:
        assert _body(schema, "/authors/", "post") == {"$ref": "#/components/schemas/NameIn"}
        assert _response(schema, "/authors/", "post", "201") == {
            "$ref": "#/components/schemas/Author"
        }
        assert _body(schema, "/authors/{id}/", "patch") == {
            "$ref": "#/components/schemas/PatchedNameIn"
        }
        assert set(_op(schema, "/authors/{id}/", "delete")["responses"]) == {"204"}
        assert _response(schema, "/authors/", "get", "200")["type"] == "array"
        assert _response(schema, "/authors/{id}/", "get", "200") == {
            "$ref": "#/components/schemas/Author"
        }

    def test_a_service_action_is_documented(self, schema: dict[str, Any]) -> None:
        assert _body(schema, "/actions/approve/", "post") == {"$ref": "#/components/schemas/NameIn"}
        assert _response(schema, "/actions/approve/", "post", "200") == {
            "$ref": "#/components/schemas/Author"
        }

    def test_a_selector_action_listing_rows_is_an_array(self, schema: dict[str, Any]) -> None:
        assert _response(schema, "/actions/recent/", "get", "200") == {
            "type": "array",
            "items": {"$ref": "#/components/schemas/Author"},
        }

    def test_a_selector_action_s_raw_rows_are_an_array(self, schema: dict[str, Any]) -> None:
        # drf-spectacular does not read the action as a list operation, so the
        # schema wraps the presenter's row itself, once.
        body = _response(schema, "/actions/named/", "get", "200")
        assert body["type"] == "array"
        assert set(body["items"]["properties"]) == {"id", "name"}
