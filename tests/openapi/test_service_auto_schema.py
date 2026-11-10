"""``ServiceAutoSchema`` documenting kernel specs, end to end through drf-spectacular.

Every view here carries the kernel's own ``ServiceSpec`` or ``SelectorSpec``,
with no ``serializer_class``: the request body is read off the spec's
Validator and the response off its presenter, never off the view's missing
``serializer_class``.

- **A ``SerializerValidator``** is documented by its serializer, under the
  component name drf-spectacular gives that class, or, where ``input_data``
  reaches a field, by a subclass less what it fills, under a name of its own;
  **any other Validator** by
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
    DEFAULT_POOL_SEEDS,
    DataclassPresenter,
    DataclassValidator,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
    UnsetType,
    Validator,
)
from drf_spectacular.drainage import reset_generator_stats
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.settings import spectacular_settings
from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers
from rest_framework.decorators import action
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


class TaskInSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=20)
    owner = serializers.CharField()
    note = serializers.CharField()


@extend_schema_serializer(component_name="Ticket")
class TicketInSerializer(TaskInSerializer): ...


@dataclass
class TaskRow:
    name: str
    owner: str
    note: str


def _untyped_fill() -> dict[str, Any]:
    return {"owner": "me"}


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


class _MayOwn(TypedDict):
    owner: str | UnsetType


def _may_own() -> _MayOwn:
    return {"owner": "me"}


@dataclass
class _OwnedRow:
    name: str
    owner: str
    note: str


class _RowFill(TypedDict):
    owner: str
    note: str | UnsetType


def _row_fill() -> _RowFill:
    return {"owner": "me", "note": "n"}


def _list_authors() -> Any:
    return Author.objects.order_by("id")


def _get_author(*, pk: int) -> Author | None:
    return Author.objects.filter(pk=pk).first()


def _create_author(*, data: Any) -> Any: ...


def _create_owned(*, data: Any, tenant: str, owner: str) -> Any: ...


def _create_stamped(*, data: Any, stamp: str) -> Any: ...


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


def _task(**fields: Any) -> ServiceSpec:
    """A spec over ``TaskInSerializer`` whose ``input_data`` fills ``owner``, may fill ``note``."""
    return _create(
        **{"validator": SerializerValidator(TaskInSerializer), "input_data": _row_fill, **fields}
    )


_ON_A_ROW: dict[str, Any] = {"service": _rename, "instance_selector_spec": _target()}


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


class _AnnotatedTaskView(ServiceCreateView):
    """The author's ``TaskInSerializer`` itself, documented beside a spec reaching nothing."""

    queryset = Author.objects.all()
    spec = _create()

    @extend_schema(request=TaskInSerializer)
    def post(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        return super().post(request, *args, **kwargs)


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
    path(
        "owned-may-decline/",
        _view(
            ServiceCreateView,
            _create(
                service=_create_owned,
                validator=DataclassValidator(_NameRow),
                reads=Parameters.of(Parameter("owner", "string", required=True)),
                kwargs=_may_own,
            ),
        ).as_view(),
    ),
    path(
        "stamped/",
        _view(
            ServiceCreateView,
            _create(
                service=_create_stamped,
                validator=DataclassValidator(_NameRow),
                reads=Parameters.of(Parameter("stamp", "string", reflected=True)),
            ),
            pool_seeds=DEFAULT_POOL_SEEDS.extend(stamp=lambda: "stamp"),
        ).as_view(),
    ),
    path(
        "owner-filled/",
        _view(
            ServiceCreateView,
            _create(validator=DataclassValidator(_OwnedRow), input_data=_row_fill),
        ).as_view(),
    ),
    path(
        "rows-filled/",
        _view(
            ServiceCreateView,
            _create(many=True, validator=DataclassValidator(_OwnedRow), input_data=_row_fill),
        ).as_view(),
    ),
    path("task/", _view(ServiceCreateView, _task()).as_view()),
    path("task-plain/", _view(ServiceCreateView, _task(input_data=None)).as_view()),
    path("task-annotated/", _AnnotatedTaskView.as_view()),
    path("task/<int:pk>/", _view(ServiceUpdateView, _task(**_ON_A_ROW)).as_view()),
    path(
        "task-partial/<int:pk>/",
        _view(ServiceUpdateView, _task(partial=True, **_ON_A_ROW)).as_view(),
    ),
    path("task-many/", _view(ServiceCreateView, _task(many=True)).as_view()),
    path("task-owned/", _view(ServiceCreateView, _task(input_data=_owner)).as_view()),
    path("task-may-own/", _view(ServiceCreateView, _task(input_data=_may_own)).as_view()),
    path("task-untyped/", _view(ServiceCreateView, _task(input_data=_untyped_fill)).as_view()),
    path(
        "task-row/",
        _view(ServiceCreateView, _task(validator=SerializerValidator(TaskRow))).as_view(),
    ),
    path(
        "task-row-plain/",
        _view(
            ServiceCreateView, _task(validator=SerializerValidator(TaskRow), input_data=None)
        ).as_view(),
    ),
    path(
        "ticket/",
        _view(
            ServiceCreateView, _task(validator=SerializerValidator(TicketInSerializer))
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

    def test_a_read_a_provider_may_decline_is_offered_and_not_required(
        self, schema: dict[str, Any]
    ) -> None:
        # The ``kwargs`` provider may answer ``owner`` with ``UNSET``, so
        # dispatch does not demand it of the caller, whose value is kept
        # beneath the provider's answer: offered, and not required.
        body = _body(schema, "/owned-may-decline/", "post")
        assert set(body["properties"]) == {"name", "owner"}
        assert body["required"] == ["name"]

    def test_a_read_named_for_a_seed_the_view_registers_is_no_body_key(
        self, schema: dict[str, Any]
    ) -> None:
        # ``stamp`` is a reflected read the view's own ``pool_seeds`` fill, so
        # the kernel withholds it under those seeds and offers it under the
        # defaults, which this body was once built with.
        assert set(_body(schema, "/stamped/", "post")["properties"]) == {"name"}

    def test_a_field_a_typed_input_data_fills_is_not_offered(self, schema: dict[str, Any]) -> None:
        # ``owner`` is always the provider's, and ``note`` it may decline.
        body = _body(schema, "/owner-filled/", "post")
        assert set(body["properties"]) == {"name", "note"}
        assert body["required"] == ["name"]

    def test_a_many_row_withholds_what_input_data_fills_and_relaxes_what_it_may(
        self, schema: dict[str, Any]
    ) -> None:
        # ``input_data`` is merged over every row: ``owner`` is never the
        # caller's in any row, and ``note`` is offered and not required.
        body = _body(schema, "/rows-filled/", "post")
        assert body["type"] == "array"
        assert set(body["items"]["properties"]) == {"name", "note"}
        assert body["items"]["required"] == ["name"]

    def test_a_delete_with_a_validator_documents_its_body(self, schema: dict[str, Any]) -> None:
        assert _body(schema, "/delete-with-reason/{id}/", "delete") == {
            "$ref": "#/components/schemas/Reason"
        }
        assert set(_body(schema, "/delete-own-reason/{id}/", "delete")["properties"]) == {"name"}

    def test_a_spec_taking_nothing_documents_no_body(self, schema: dict[str, Any]) -> None:
        assert "requestBody" not in _op(schema, "/delete/{id}/", "delete")
        assert "requestBody" not in _op(schema, "/create-no-input/", "post")


def _asked(schema: dict[str, Any], body: dict[str, Any]) -> tuple[set[str], set[str]]:
    """The fields a documented body offers, and those it requires."""
    component = _component(schema, body["$ref"])
    return set(component["properties"]), set(component.get("required", ()))


def _options_asked(route: str, method: str, **captures: Any) -> tuple[set[str], set[str]]:
    """The fields OPTIONS describes ``method`` of ``route`` as taking, and those it requires."""
    resolved = next(pattern for pattern in urlpatterns if str(pattern.pattern) == route)
    response = resolved.callback(APIRequestFactory().options("/"), **captures)
    described = response.data["actions"][method]
    return set(described["properties"]), set(described.get("required", ()))


class TestASerializerBodyInputDataReaches:
    """A ``SerializerValidator`` body less what ``input_data`` fills, under a name of its own."""

    def test_the_body_agrees_with_options(self, schema: dict[str, Any]) -> None:
        # ``owner`` is always ``input_data``'s, so it is not offered, and
        # ``note`` it may decline, so it is offered and not required: what
        # OPTIONS already says of the same route.
        assert _asked(schema, _body(schema, "/task/", "post")) == _options_asked("task/", "POST")
        assert _asked(schema, _body(schema, "/task/{id}/", "put")) == _options_asked(
            "task/<int:pk>/", "PUT", pk=1
        )
        assert _asked(schema, _body(schema, "/task/", "post")) == ({"name", "note"}, {"name"})

    def test_it_is_a_component_of_its_own(self, schema: dict[str, Any]) -> None:
        assert _body(schema, "/task/", "post") == {
            "$ref": "#/components/schemas/TaskInLessOwner__OptionalNote"
        }

    def test_a_spec_reaching_nothing_keeps_the_author_s_component(
        self, schema: dict[str, Any]
    ) -> None:
        body = _body(schema, "/task-plain/", "post")
        assert body == {"$ref": "#/components/schemas/TaskIn"}
        assert _asked(schema, body) == ({"name", "owner", "note"}, {"name", "owner", "note"})

    def test_a_spec_reaching_nothing_is_documented_by_the_author_s_class(
        self, schema: dict[str, Any]
    ) -> None:
        # ``task-annotated/`` documents ``TaskInSerializer`` itself under
        # ``TaskIn``; a second class under that name would be a collision
        # (test_no_two_components_share_a_name).
        assert _body(schema, "/task-annotated/", "post") == {"$ref": "#/components/schemas/TaskIn"}

    def test_one_filled_field_and_one_relaxed_field_are_named_apart(
        self, schema: dict[str, Any]
    ) -> None:
        owned = _body(schema, "/task-owned/", "post")
        may_own = _body(schema, "/task-may-own/", "post")
        assert owned == {"$ref": "#/components/schemas/TaskInLessOwner"}
        assert may_own == {"$ref": "#/components/schemas/TaskInOptionalOwner"}
        assert _asked(schema, owned) == ({"name", "note"}, {"name", "note"})
        assert _asked(schema, may_own) == ({"name", "owner", "note"}, {"name", "note"})

    def test_a_patch_and_a_partial_spec_are_its_patched_form(self, schema: dict[str, Any]) -> None:
        ref = {"$ref": "#/components/schemas/PatchedTaskInLessOwner__OptionalNote"}
        assert _body(schema, "/task/{id}/", "patch") == ref
        assert _body(schema, "/task-partial/{id}/", "put") == ref
        assert _asked(schema, ref) == ({"name", "note"}, set())

    def test_a_many_spec_takes_an_array_of_its_rows(self, schema: dict[str, Any]) -> None:
        assert _body(schema, "/task-many/", "post") == {
            "type": "array",
            "items": {"$ref": "#/components/schemas/TaskInLessOwner__OptionalNote"},
        }

    def test_an_untyped_input_data_requires_no_field(self, schema: dict[str, Any]) -> None:
        # It may fill any field, so dispatch demands none of the caller and
        # OPTIONS requires none: every field is offered, none required.
        body = _body(schema, "/task-untyped/", "post")
        assert body == {"$ref": "#/components/schemas/TaskInOptionalName_Note_Owner"}
        assert _asked(schema, body) == ({"name", "owner", "note"}, set())
        assert _asked(schema, body) == _options_asked("task-untyped/", "POST")

    @pytest.mark.django_db
    def test_the_serializer_still_refuses_a_field_an_untyped_input_data_left_out(self) -> None:
        # Required of no caller by the schema, and still validated: the
        # provider fills ``owner`` only, so the serializer refuses the missing
        # ``name``.
        view = next(p for p in urlpatterns if str(p.pattern) == "task-untyped/").callback
        response = view(APIRequestFactory().post("/", {"note": "n"}, format="json"))
        assert response.status_code == 400
        assert set(response.data) == {"name"}

    def test_a_dataclass_gets_a_component_of_its_own(self, schema: dict[str, Any]) -> None:
        # drf-spectacular identifies a dataclass's component by the dataclass,
        # so under the base's name it would reuse that component silently.
        derived = _body(schema, "/task-row/", "post")
        base = _body(schema, "/task-row-plain/", "post")
        assert derived == {"$ref": "#/components/schemas/TaskRowLessOwner__OptionalNote"}
        assert base == {"$ref": "#/components/schemas/TaskRow"}
        assert _asked(schema, derived) == ({"name", "note"}, {"name"})
        assert _asked(schema, base) == ({"name", "owner", "note"}, {"name", "owner", "note"})

    def test_a_base_s_component_name_is_the_stem_and_not_the_name(
        self, schema: dict[str, Any]
    ) -> None:
        # ``component_name`` is inherited, and outranks ``Meta.ref_name``.
        assert _body(schema, "/ticket/", "post") == {
            "$ref": "#/components/schemas/TicketLessOwner__OptionalNote"
        }

    def test_no_two_components_share_a_name(self, capsys: pytest.CaptureFixture[str]) -> None:
        # A plain serializer under its base's name warns, and the first
        # component documented wins.
        reset_generator_stats()
        SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)
        assert "identical names" not in capsys.readouterr().err


class TestTheResponse:
    def test_a_create_answers_201_with_its_presenter_s_serializer(
        self, schema: dict[str, Any]
    ) -> None:
        assert _response(schema, "/create/", "post", "201") == {
            "$ref": "#/components/schemas/Author"
        }
        assert set(_op(schema, "/create/", "post")["responses"]) == {"201", "400"}

    def test_the_view_s_status_is_documented(self, schema: dict[str, Any]) -> None:
        assert set(_op(schema, "/create-202/", "post")["responses"]) == {"202", "400"}

    def test_a_callable_status_documents_the_action_s_default(self, schema: dict[str, Any]) -> None:
        assert set(_op(schema, "/create-callable/", "post")["responses"]) == {"201", "400"}

    def test_a_spec_that_may_present_nothing_documents_its_204(
        self, schema: dict[str, Any]
    ) -> None:
        responses = _op(schema, "/create-may-be-none/", "post")["responses"]
        assert set(responses) == {"201", "204", "400"}
        assert "content" not in responses["204"]

    def test_no_presenter_documents_no_body_at_the_status_and_the_204(
        self, schema: dict[str, Any]
    ) -> None:
        # The wire is pinned beside the document in test_no_presenter_status.
        responses = _op(schema, "/create-bare/", "post")["responses"]
        assert set(responses) == {"201", "204", "400"}
        assert "content" not in responses["201"]
        assert "content" not in responses["204"]

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
        assert set(responses) == {"201", "400"}
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

    def test_an_undeclared_service_error_is_not_documented_with_or_without_a_validator(
        self, schema: dict[str, Any]
    ) -> None:
        # Where the spec declares it, the 422 and its ``ServiceError`` body
        # are held by test_service_error_declared, and end to end by
        # test_validator_refusal_schema.
        assert "422" not in _op(schema, "/create/", "post")["responses"]
        responses = _op(schema, "/create-no-input/", "post")["responses"]
        assert "422" not in responses
        assert "400" not in responses


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


class _PlainViewSet(GenericViewSet):
    """A DRF action beside no spec at all: the schema class documents it as DRF's."""

    serializer_class = NameInSerializer

    @action(detail=False, methods=["post"])
    def plain(self, request: Any) -> Any: ...


def test_an_operation_with_no_service_spec_documents_drf_s_own_request_body() -> None:
    router = DefaultRouter()
    router.register("plain", _PlainViewSet, basename="plain")
    generated = SchemaGenerator(patterns=router.urls).get_schema(request=None, public=True)

    assert _body(generated, "/plain/plain/", "post") == {"$ref": "#/components/schemas/NameIn"}


def test_a_split_request_component_is_named_from_the_author_s_stem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # drf-spectacular appends ``Request`` to every request component, the
    # derived one included, so the stem is read without it.
    monkeypatch.setattr(spectacular_settings, "COMPONENT_SPLIT_REQUEST", True)
    schema = SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)
    assert _body(schema, "/task/", "post") == {
        "$ref": "#/components/schemas/TaskInLessOwner__OptionalNoteRequest"
    }
