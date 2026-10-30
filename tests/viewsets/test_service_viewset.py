"""``ServiceViewSet`` serving kernel specs from ``action_specs``.

Every entry here is the kernel's own ``ServiceSpec`` or ``SelectorSpec``, with
the DRF seats ``SerializerValidator`` and ``SerializerPresenter``, and every
test drives the viewset through ``as_view()``, so each fails against a tree
whose ``as_view()`` refuses a kernel spec in ``action_specs``.

The actions dispatch through the standalone views' own edge
(``dispatch_mutation_for_spec`` and ``dispatch_kernel_selector``), and
``as_view()`` asks each entry the standalone views' own kernel checks
(``validate_mutation_view_spec`` / ``validate_selector_view_spec``), keyed by
the action the entry serves.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import (
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceViewSet
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _NameIn(serializers.Serializer):
    name = serializers.CharField(max_length=20)


class _Deny(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return False


class _DenyAll(PermissionCheck):
    """A kernel check refusing every principal."""

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return False

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        return False


def _list_authors() -> Any:
    return Author.objects.order_by("id")


def _get_author(*, pk: int) -> Author | None:
    return Author.objects.filter(pk=pk).first()


def _create_author(*, data: dict[str, Any]) -> Author:
    return Author.objects.create(name=data["name"])


def _rename(*, instance: Author, data: dict[str, Any]) -> Author:
    instance.name = data["name"]
    instance.save(update_fields=["name"])
    return instance


def _delete(*, instance: Author) -> None:
    instance.delete()


_BY_PK = Parameters.of(Parameter("pk", "integer", required=True))
_PRESENTER = SerializerPresenter(AuthorSerializer)


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


def _target() -> SelectorSpec:
    """A write's target lookup: a nested selector, which declares no ``permissions``."""
    return SelectorSpec(kind=SelectorKind.RETRIEVE, selector=_get_author, reads=_BY_PK)


def _write(**fields: Any) -> ServiceSpec:
    return ServiceSpec(**{"permissions": _OPEN, **fields})


def _create(**fields: Any) -> ServiceSpec:
    defaults: dict[str, Any] = {
        "service": _create_author,
        "validator": SerializerValidator(_NameIn),
        "presenter": _PRESENTER,
    }
    return _write(**{**defaults, **fields})


def _update(**fields: Any) -> ServiceSpec:
    defaults: dict[str, Any] = {
        "service": _rename,
        "validator": SerializerValidator(_NameIn),
        "presenter": _PRESENTER,
        "instance_selector_spec": _target(),
    }
    return _write(**{**defaults, **fields})


def _destroy(**fields: Any) -> ServiceSpec:
    return _write(**{"service": _delete, "instance_selector_spec": _target(), **fields})


class _AuthorViewSet(ServiceViewSet):
    queryset = Author.objects.all()
    action_specs = {
        "list": _list(),
        "retrieve": _retrieve(),
        "create": _create(),
        "update": _update(),
        "destroy": _destroy(),
    }


def _viewset(base: type = ServiceViewSet, **attrs: Any) -> type:
    return type("_ViewSet", (base,), {"queryset": Author.objects.all(), **attrs})


def _call(viewset: type, method: str, action: str, body: Any = None, **kwargs: Any) -> Response:
    view = viewset.as_view({method: action})
    request = getattr(factory, method)("/", body, format="json")
    return view(request, **kwargs)


class TestTheActions:
    def test_list_is_presented_by_the_spec(self) -> None:
        Author.objects.create(name="a")
        Author.objects.create(name="b")
        response = _call(_AuthorViewSet, "get", "list")
        assert response.status_code == 200
        assert [row["name"] for row in response.data] == ["a", "b"]

    def test_retrieve_is_presented_by_the_spec(self) -> None:
        author = Author.objects.create(name="a")
        response = _call(_AuthorViewSet, "get", "retrieve", pk=author.pk)
        assert response.status_code == 200
        assert response.data == {"id": author.pk, "name": "a"}

    def test_retrieve_of_no_row_is_404(self) -> None:
        assert _call(_AuthorViewSet, "get", "retrieve", pk=999).status_code == 404

    def test_create_validates_runs_and_presents(self) -> None:
        response = _call(_AuthorViewSet, "post", "create", {"name": "Ada"})
        assert response.status_code == 201
        assert response.data == {"id": Author.objects.get().pk, "name": "Ada"}

    def test_create_refuses_an_invalid_body(self) -> None:
        response = _call(_AuthorViewSet, "post", "create", {"name": "x" * 30})
        assert response.status_code == 400
        assert "name" in response.data
        assert not Author.objects.exists()

    def test_update_acts_on_the_spec_s_own_target(self) -> None:
        author = Author.objects.create(name="a")
        response = _call(_AuthorViewSet, "put", "update", {"name": "b"}, pk=author.pk)
        assert response.status_code == 200
        assert response.data == {"id": author.pk, "name": "b"}

    def test_update_of_no_row_is_404(self) -> None:
        assert _call(_AuthorViewSet, "put", "update", {"name": "b"}, pk=999).status_code == 404

    def test_patch_falls_back_to_the_update_entry(self) -> None:
        author = Author.objects.create(name="a")
        response = _call(_AuthorViewSet, "patch", "partial_update", {"name": "b"}, pk=author.pk)
        assert response.status_code == 200, response.data
        assert response.data == {"id": author.pk, "name": "b"}

    def test_destroy_answers_204(self) -> None:
        author = Author.objects.create(name="a")
        response = _call(_AuthorViewSet, "delete", "destroy", pk=author.pk)
        assert response.status_code == 204
        assert not Author.objects.exists()


class TestPresentation:
    def test_a_list_spec_with_no_presenter_renders_the_view_s_serializer(self) -> None:
        Author.objects.create(name="a")
        viewset = _viewset(
            serializer_class=AuthorSerializer, action_specs={"list": _list(presenter=None)}
        )
        response = _call(viewset, "get", "list")
        assert response.status_code == 200
        assert [row["name"] for row in response.data] == ["a"]

    def test_a_retrieve_spec_with_no_presenter_renders_the_view_s_serializer(self) -> None:
        author = Author.objects.create(name="a")
        viewset = _viewset(
            serializer_class=AuthorSerializer, action_specs={"retrieve": _retrieve(presenter=None)}
        )
        response = _call(viewset, "get", "retrieve", pk=author.pk)
        assert response.data == {"id": author.pk, "name": "a"}

    def test_a_paginated_list_presents_the_page_s_rows(self) -> None:
        for name in "abc":
            Author.objects.create(name=name)

        class _Pages(PageNumberPagination):
            page_size = 2

        viewset = _viewset(pagination_class=_Pages, action_specs={"list": _list()})
        response = _call(viewset, "get", "list")
        assert response.data["count"] == 3
        assert [row["name"] for row in response.data["results"]] == ["a", "b"]

    def test_a_list_is_dispatched_once(self) -> None:
        calls: list[int] = []

        def counted() -> Any:
            calls.append(1)
            return _list_authors()

        viewset = _viewset(action_specs={"list": _list(selector=counted)})
        assert _call(viewset, "get", "list").status_code == 200
        assert calls == [1]

    def test_an_allow_none_retrieve_of_no_row_is_json_null(self) -> None:
        viewset = _viewset(action_specs={"retrieve": _retrieve(allow_none=True)})
        response = _call(viewset, "get", "retrieve", pk=999)
        assert response.status_code == 200
        assert response.render().content == b"null"

    def test_an_update_whose_service_returns_nothing_presents_its_target(self) -> None:
        author = Author.objects.create(name="a")

        def touch(*, instance: Author, data: dict[str, Any]) -> None:
            instance.name = data["name"]
            instance.save(update_fields=["name"])

        viewset = _viewset(action_specs={"update": _update(service=touch)})
        response = _call(viewset, "put", "update", {"name": "b"}, pk=author.pk)
        assert response.status_code == 200
        assert response.data == {"id": author.pk, "name": "b"}

    def test_the_view_s_success_status_answers_the_action(self) -> None:
        viewset = _viewset(success_status=202, action_specs={"create": _create()})
        assert _call(viewset, "post", "create", {"name": "Ada"}).status_code == 202

    def test_the_view_s_response_finalizer_runs(self) -> None:
        def finalize(*, response: Response) -> Response:
            response["X-Done"] = "yes"
            return response

        viewset = _viewset(response_finalizer=finalize, action_specs={"create": _create()})
        assert _call(viewset, "post", "create", {"name": "Ada"})["X-Done"] == "yes"


class TestPermissions:
    def test_the_spec_s_own_checks_refuse(self) -> None:
        viewset = _viewset(action_specs={"create": _create(permissions=(_DenyAll(),))})
        assert _call(viewset, "post", "create", {"name": "Ada"}).status_code == 403
        assert not Author.objects.exists()

    def test_the_view_s_own_classes_refuse_before_the_spec_runs(self) -> None:
        viewset = _viewset(permission_classes=[_Deny], action_specs={"create": _create()})
        assert _call(viewset, "post", "create", {"name": "Ada"}).status_code == 403
        assert not Author.objects.exists()

    def test_a_kernel_entry_takes_the_view_s_own_classes(self) -> None:
        viewset = _viewset(permission_classes=[_Deny], action_specs={"list": _list()})
        assert _call(viewset, "get", "list").status_code == 403

    def test_a_retrieve_s_object_permission_is_the_view_s(self) -> None:
        author = Author.objects.create(name="a")

        class _NoRows(BasePermission):
            def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
                return False

        viewset = _viewset(permission_classes=[_NoRows], action_specs={"retrieve": _retrieve()})
        assert _call(viewset, "get", "retrieve", pk=author.pk).status_code == 403

    def test_an_update_s_target_is_asked_the_view_s_object_permission(self) -> None:
        author = Author.objects.create(name="a")

        class _NoRows(BasePermission):
            def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
                return False

        viewset = _viewset(permission_classes=[_NoRows], action_specs={"update": _update()})
        response = _call(viewset, "put", "update", {"name": "b"}, pk=author.pk)
        assert response.status_code == 403
        assert Author.objects.get().name == "a"


class TestHooks:
    def test_the_spec_s_kwargs_provider_reaches_the_service(self) -> None:
        seen: list[str] = []

        def create(*, data: dict[str, Any], tag: str) -> Author:
            seen.append(tag)
            return _create_author(data=data)

        spec = _create(service=create, kwargs=lambda: {"tag": "spec"})
        viewset = _viewset(action_specs={"create": spec})
        assert _call(viewset, "post", "create", {"name": "Ada"}).status_code == 201
        assert seen == ["spec"]

    def test_a_catch_all_hook_fills_a_keyword_the_seeds_cannot_see(self) -> None:
        seen: list[str] = []

        def create(*, data: dict[str, Any], tag: str) -> Author:
            seen.append(tag)
            return _create_author(data=data)

        viewset = _viewset(
            action_specs={"create": _create(service=create)},
            get_service_kwargs=lambda self: {"tag": "view"},
        )
        assert _call(viewset, "post", "create", {"name": "Ada"}).status_code == 201
        assert seen == ["view"]

    def test_a_per_action_hook_fills_a_keyword_the_seeds_cannot_see(self) -> None:
        seen: list[str] = []

        def create(*, data: dict[str, Any], tag: str) -> Author:
            seen.append(tag)
            return _create_author(data=data)

        viewset = _viewset(
            action_specs={"create": _create(service=create)},
            get_create_service_kwargs=lambda self: {"tag": "action"},
        )
        assert _call(viewset, "post", "create", {"name": "Ada"}).status_code == 201
        assert seen == ["action"]


class TestUnconfigured:
    @pytest.mark.parametrize(
        ("method", "action", "kwargs"),
        [
            ("post", "create", {}),
            ("put", "update", {"pk": 1}),
            ("patch", "partial_update", {"pk": 1}),
            ("delete", "destroy", {"pk": 1}),
        ],
    )
    def test_an_action_with_no_entry_is_405(
        self, method: str, action: str, kwargs: dict[str, Any]
    ) -> None:
        viewset = _viewset(action_specs={"list": _list()})
        assert _call(viewset, method, action, {}, **kwargs).status_code == 405

    def test_a_partial_update_only_entry_leaves_put_405(self) -> None:
        author = Author.objects.create(name="a")
        viewset = _viewset(action_specs={"partial_update": _update()})
        assert _call(viewset, "put", "update", {"name": "b"}, pk=author.pk).status_code == 405
        response = _call(viewset, "patch", "partial_update", {"name": "b"}, pk=author.pk)
        assert response.status_code == 200


class TestAsView:
    @pytest.mark.parametrize("action", ["create", "update", "partial_update", "destroy"])
    def test_a_selector_spec_under_a_write_action_is_refused(self, action: str) -> None:
        viewset = _viewset(action_specs={action: _list()})
        with pytest.raises(ImproperlyConfigured, match="serves a ServiceSpec"):
            viewset.as_view({"get": "list"})

    @pytest.mark.parametrize("action", ["list", "retrieve"])
    def test_a_service_spec_under_a_read_action_is_refused(self, action: str) -> None:
        viewset = _viewset(action_specs={action: _create()})
        with pytest.raises(ImproperlyConfigured, match="serves a SelectorSpec"):
            viewset.as_view({"get": "list"})

    def test_a_list_spec_under_retrieve_is_refused(self) -> None:
        viewset = _viewset(action_specs={"retrieve": _list()})
        with pytest.raises(ImproperlyConfigured, match="expects"):
            viewset.as_view({"get": "list"})

    def test_the_refusal_names_the_action(self) -> None:
        viewset = _viewset(action_specs={"create": _list()})
        with pytest.raises(ImproperlyConfigured, match=r"action_specs\['create'\]"):
            viewset.as_view({"get": "list"})

    @pytest.mark.parametrize("action", ["update", "partial_update", "destroy"])
    def test_a_detail_action_with_no_target_is_refused(self, action: str) -> None:
        viewset = _viewset(action_specs={action: _write(service=_delete)})
        with pytest.raises(ImproperlyConfigured, match="declares no target selector"):
            viewset.as_view({"get": "list"})

    @pytest.mark.parametrize("action", ["update", "partial_update", "destroy"])
    def test_a_nested_selector_s_permissions_are_refused(self, action: str) -> None:
        nested = _retrieve(presenter=None)
        viewset = _viewset(action_specs={action: _update(instance_selector_spec=nested)})
        with pytest.raises(
            ImproperlyConfigured,
            match=rf"action_specs\['{action}'\]\.spec\.instance_selector_spec declares permissions",
        ):
            viewset.as_view({"get": "list"})

    def test_a_create_with_no_target_passes(self) -> None:
        assert callable(_viewset(action_specs={"create": _create()}).as_view({"post": "create"}))

    def test_a_keyword_nothing_fills_is_refused(self) -> None:
        def create(*, tag: str) -> None: ...

        viewset = _viewset(action_specs={"create": _write(service=create)})
        with pytest.raises(ImproperlyConfigured, match="tag"):
            viewset.as_view({"post": "create"})

    def test_a_per_action_hook_for_another_action_fills_nothing(self) -> None:
        def create(*, tag: str) -> None: ...

        viewset = _viewset(
            action_specs={"create": _write(service=create)},
            get_update_service_kwargs=lambda self: {"tag": "x"},
        )
        with pytest.raises(ImproperlyConfigured, match="tag"):
            viewset.as_view({"post": "create"})

    def test_a_list_selector_requiring_a_keyword_nothing_fills_is_refused(self) -> None:
        viewset = _viewset(action_specs={"list": _list(selector=lambda *, owner: None)})
        with pytest.raises(ImproperlyConfigured, match="owner"):
            viewset.as_view({"get": "list"})

    @pytest.mark.parametrize("action", ["list", "retrieve"])
    def test_get_selector_kwargs_beside_a_kernel_selector_is_refused(self, action: str) -> None:
        entry = _list() if action == "list" else _retrieve()
        viewset = _viewset(action_specs={action: entry}, get_selector_kwargs=lambda self: {"x": 1})
        with pytest.raises(ImproperlyConfigured, match="get_selector_kwargs"):
            viewset.as_view({"get": action})

    def test_a_per_action_selector_hook_beside_a_kernel_selector_is_refused(self) -> None:
        viewset = _viewset(
            action_specs={"retrieve": _retrieve()},
            get_retrieve_selector_kwargs=lambda self: {"x": 1},
        )
        with pytest.raises(ImproperlyConfigured, match="get_retrieve_selector_kwargs"):
            viewset.as_view({"get": "retrieve"})

    def test_the_view_s_success_status_is_checked(self) -> None:
        viewset = _viewset(success_status="201", action_specs={"create": _create()})
        with pytest.raises(ImproperlyConfigured):
            viewset.as_view({"post": "create"})

    def test_a_kernel_spec_under_a_custom_key_is_refused(self) -> None:
        """A custom key feeds ``get_permissions`` and the serializer resolver
        only, and a kernel spec's checks are asked by ``dispatch`` alone, so
        such an entry would guard nothing: ``@service_action`` /
        ``@selector_action`` are the way to serve one."""
        viewset = _viewset(action_specs={"publish": _create()})
        with pytest.raises(ImproperlyConfigured, match="service_action"):
            viewset.as_view({"post": "create"})
