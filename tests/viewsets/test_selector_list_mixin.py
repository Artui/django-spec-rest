"""``SelectorListMixin.get_queryset`` beside the actions it does not serve.

DRF's ``DjangoModelPermissions`` asks ``get_queryset()`` on every action, for
the model whose permissions it checks. Off ``list`` the mixin answers DRF's own
``get_queryset()`` (the viewset's ``queryset``), so a ``retrieve``, a ``PATCH``,
a ``@selector_action`` or an OPTIONS beside a list spec answers as its own spec
says, never the list's refusal. On ``list`` the dispatch the permission class
asked for is the one ``list`` presents, so the list's selector runs once.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.db.models import QuerySet
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
from rest_framework.decorators import action
from rest_framework.permissions import DjangoModelPermissions
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest import SelectorViewSet, ServiceViewSet, selector_action
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_PRESENTER = SerializerPresenter(AuthorSerializer)
_BY_PK = Parameters.of(Parameter("pk", "integer", required=True))


class _NameIn(serializers.Serializer):
    name = serializers.CharField()


class _DenyAll(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return False


def _authors() -> QuerySet[Author]:
    return Author.objects.order_by("id")


def _named(*, name: str) -> QuerySet[Author]:
    return Author.objects.filter(name=name).order_by("id")


def _rename(*, instance: Author, data: dict[str, Any]) -> Author:
    instance.name = data["name"]
    instance.save(update_fields=["name"])
    return instance


def _list(**fields: Any) -> SelectorSpec:
    defaults: dict[str, Any] = {"selector": _authors, "permissions": _OPEN, "presenter": _PRESENTER}
    return SelectorSpec(kind=SelectorKind.LIST, **{**defaults, **fields})


# A list spec whose required read no other action's request carries: on main,
# asking it for a retrieve's queryset answered the retrieve 400.
_NEEDS_A_NAME = _list(
    selector=_named, reads=Parameters.of(Parameter("name", "string", required=True))
)
# A list spec whose own check refuses everyone: on main, a retrieve answered 403.
_DENIED = _list(permissions=(_DenyAll(),))

_RETRIEVE = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
    reads=_BY_PK,
    permissions=_OPEN,
    presenter=_PRESENTER,
)
_UPDATE = ServiceSpec(
    service=_rename,
    permissions=_OPEN,
    validator=SerializerValidator(_NameIn),
    presenter=_PRESENTER,
    instance_selector_spec=SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
        reads=_BY_PK,
    ),
)


def _viewset(list_spec: SelectorSpec, base: type = ServiceViewSet, **attrs: Any) -> Any:
    namespace: dict[str, Any] = {
        "queryset": Author.objects.all(),
        "permission_classes": [DjangoModelPermissions],
        "action_specs": {"list": list_spec, "retrieve": _RETRIEVE, "partial_update": _UPDATE},
        **attrs,
    }
    return type("_ViewSet", (base,), namespace)


@pytest.fixture
def admin() -> Any:
    """``DjangoModelPermissions`` refuses an anonymous caller; a superuser holds every perm."""
    return get_user_model().objects.create_superuser("admin", "admin@example.com", "pw")


def _call(
    viewset: Any, user: Any, method: str, action_name: str, body: Any = None, **kwargs: Any
) -> Response:
    request = getattr(factory, method)("/", body, format="json")
    force_authenticate(request, user)
    return viewset.as_view({method: action_name})(request, **kwargs)


class TestOffList:
    @pytest.mark.parametrize("list_spec", [_NEEDS_A_NAME, _DENIED], ids=["required-read", "denied"])
    def test_retrieve_answers_as_its_own_spec_says(self, admin: Any, list_spec: Any) -> None:
        author = Author.objects.create(name="a")
        response = _call(_viewset(list_spec), admin, "get", "retrieve", pk=author.pk)
        assert response.status_code == 200
        assert response.data == {"id": author.pk, "name": "a"}

    @pytest.mark.parametrize("list_spec", [_NEEDS_A_NAME, _DENIED], ids=["required-read", "denied"])
    def test_a_patch_answers_as_its_own_spec_says(self, admin: Any, list_spec: Any) -> None:
        author = Author.objects.create(name="a")
        viewset = _viewset(list_spec)
        response = _call(viewset, admin, "patch", "partial_update", {"name": "b"}, pk=author.pk)
        assert response.status_code == 200
        assert response.data == {"id": author.pk, "name": "b"}
        assert Author.objects.get().name == "b"

    def test_a_selector_action_answers_as_its_own_spec_says(self, admin: Any) -> None:
        Author.objects.create(name="a")

        class _ViewSet(SelectorViewSet):
            queryset = Author.objects.all()
            permission_classes = [DjangoModelPermissions]
            action_specs = {"list": _NEEDS_A_NAME}

            @selector_action(_list())
            def everyone(self, request: Any) -> None:
                """Stubbed."""

        response = _call(_ViewSet, admin, "get", "everyone")
        assert response.status_code == 200
        assert [row["name"] for row in response.data] == ["a"]

    def test_options_answers_beside_a_list_spec_with_a_required_read(self, admin: Any) -> None:
        """OPTIONS is the implicit ``metadata`` action, and a CORS preflight."""
        request = factory.options("/")
        force_authenticate(request, admin)
        response = _viewset(_NEEDS_A_NAME).as_view({"get": "list"})(request)
        assert response.status_code == 200

    def test_get_queryset_answers_the_viewset_s_queryset(self, admin: Any) -> None:
        """A handler of the view's own reading ``get_queryset()`` off ``list``
        reads the viewset's ``queryset``, as on DRF's own viewset, never the
        list spec's set."""
        Author.objects.create(name="a")

        class _ViewSet(SelectorViewSet):
            queryset = Author.objects.none()
            action_specs = {"list": _list()}

            @action(detail=False)
            def names(self, request: Any) -> Response:
                return Response([author.name for author in self.get_queryset()])

        assert _call(_ViewSet, admin, "get", "names").data == []

    def test_drf_s_own_retrieve_reaches_the_viewset_s_rows_not_the_list_s(self) -> None:
        """A ``retrieve`` with no spec is DRF's: its ``get_object()`` looks the
        row up in the viewset's ``queryset``, so a row the list selector leaves
        out is reached. Scoping kept in the list selector alone scopes the list
        alone."""
        Author.objects.create(name="mine")
        theirs = Author.objects.create(name="theirs")

        class _ViewSet(SelectorViewSet):
            queryset = Author.objects.all()
            serializer_class = AuthorSerializer
            action_specs = {"list": _list(selector=lambda: Author.objects.filter(name="mine"))}

        request = factory.get("/")
        response = _ViewSet.as_view({"get": "retrieve"})(request, pk=theirs.pk)
        assert response.status_code == 200
        assert response.data == {"id": theirs.pk, "name": "theirs"}
        listed = _ViewSet.as_view({"get": "list"})(factory.get("/"))
        assert [row["name"] for row in listed.data] == ["mine"]

    def test_no_queryset_is_drf_s_own_assertion(self, admin: Any) -> None:
        """DRF's contract: ``DjangoModelPermissions`` needs a ``queryset``
        attribute, and off ``list`` the mixin answers DRF's ``get_queryset()``."""
        author = Author.objects.create(name="a")
        viewset = _viewset(_list(), queryset=None)
        with pytest.raises(AssertionError, match="should either include a `queryset` attribute"):
            _call(viewset, admin, "get", "retrieve", pk=author.pk)


class TestOnList:
    def test_the_list_selector_runs_once_under_django_model_permissions(self, admin: Any) -> None:
        calls: list[int] = []

        def counted() -> QuerySet[Author]:
            calls.append(1)
            return _authors()

        Author.objects.create(name="a")
        response = _call(_viewset(_list(selector=counted)), admin, "get", "list")
        assert response.status_code == 200
        assert [row["name"] for row in response.data] == ["a"]
        assert calls == [1]

    def test_the_list_spec_s_read_still_answers_its_list(self, admin: Any) -> None:
        Author.objects.create(name="a")
        Author.objects.create(name="b")
        viewset = _viewset(_NEEDS_A_NAME)
        request = factory.get("/", {"name": "b"})
        force_authenticate(request, admin)
        response = viewset.as_view({"get": "list"})(request)
        assert [row["name"] for row in response.data] == ["b"]

    def test_the_list_s_own_refusal_still_answers_its_list(self, admin: Any) -> None:
        assert _call(_viewset(_NEEDS_A_NAME), admin, "get", "list").status_code == 400
        assert _call(_viewset(_DENIED), admin, "get", "list").status_code == 403

    def test_get_queryset_on_list_is_the_set_the_list_presents(self) -> None:
        """Without a permission class asking first, ``get_queryset()`` on
        ``list`` still answers the spec's set, and ``list`` presents that
        same dispatch rather than running the selector again."""
        calls: list[int] = []

        def counted() -> QuerySet[Author]:
            calls.append(1)
            return _authors()

        Author.objects.create(name="a")
        view = _viewset(_list(selector=counted))()
        view.action_map = {"get": "list"}
        view.setup(factory.get("/"))
        view.request = view.initialize_request(view.request)
        view.format_kwarg = None
        assert [author.name for author in view.get_queryset()] == ["a"]
        assert [row["name"] for row in view.list(view.request).data] == ["a"]
        assert calls == [1]

    def test_a_dispatch_that_raised_is_not_kept(self) -> None:
        """A refused dispatch keeps nothing: asked again for the same request,
        the spec dispatches again rather than answering a stale set."""
        calls: list[int] = []

        def flaky() -> QuerySet[Author]:
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("first call refused")
            return _authors()

        view = _viewset(_list(selector=flaky))()
        view.action_map = {"get": "list"}
        view.format_kwarg = None
        view.setup(factory.get("/"))
        view.request = view.initialize_request(view.request)
        with pytest.raises(RuntimeError, match="first call refused"):
            view.get_queryset()
        assert list(view.get_queryset()) == []
        assert calls == [1, 1]

    def test_the_dispatch_is_the_request_s_own(self) -> None:
        """The one dispatch is kept for the request it answered: a view
        instance handed a second request (DRF builds one instance per request,
        but a test or a subclass may reuse it) dispatches again."""
        calls: list[int] = []

        def counted() -> QuerySet[Author]:
            calls.append(1)
            return _authors()

        view = _viewset(_list(selector=counted))()
        view.action_map = {"get": "list"}
        view.format_kwarg = None
        for _ in range(2):
            view.setup(factory.get("/"))
            view.request = view.initialize_request(view.request)
            view.get_queryset()
            view.get_queryset()
        assert calls == [1, 1]
