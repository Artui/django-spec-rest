from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.decorators import action as drf_action
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest import (
    SelectorRetrieveView,
    SelectorViewSet,
    ServiceViewSet,
    selector_action,
    service_action,
)
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author

_OPEN = (Unrestricted(),)


class _NameIn(serializers.Serializer):
    name = serializers.CharField()


def _reads(name: str) -> Parameters:
    return Parameters.of(Parameter(name, "integer", required=True))


def _row(*, by: str | None = "pk", nested: bool = False) -> SelectorSpec:
    """A retrieve selector reading ``by``, or reading nothing where ``by`` is ``None``."""
    permissions = None if nested else _OPEN
    if by is None:
        return SelectorSpec(
            kind=SelectorKind.RETRIEVE, selector=lambda: None, permissions=permissions
        )

    def lookup(**kwargs: Any) -> Any:
        return Author.objects.filter(pk=kwargs[by]).first()

    return SelectorSpec(
        kind=SelectorKind.RETRIEVE, selector=lookup, reads=_reads(by), permissions=permissions
    )


def _service(*, instance: Any) -> None: ...


def _write(*, by: str | None = "pk", **fields: Any) -> ServiceSpec:
    return ServiceSpec(
        service=_service,
        permissions=_OPEN,
        instance_selector_spec=_row(by=by, nested=True),
        **fields,
    )


def _viewset(base: type = ServiceViewSet, **attrs: Any) -> type:
    return type("_Notes", (base,), {"queryset": Author.objects.all(), **attrs})


def _mount(viewset: type, actions: dict[str, str]) -> Any:
    """``viewset`` mounted as a router mounts its detail route."""
    return viewset.as_view(actions, detail=True)


def _refusal(viewset: type, actions: dict[str, str]) -> str:
    with pytest.raises(ImproperlyConfigured) as raised:
        _mount(viewset, actions)
    return str(raised.value)


class TestARowLookupMissingTheCaptureIsRefused:
    def test_a_retrieve_selector(self) -> None:
        viewset = _viewset(SelectorViewSet, action_specs={"retrieve": _row(by=None)})
        message = _refusal(viewset, {"get": "retrieve"})
        assert message.startswith("_Notes.retrieve: the router captures the lookup as 'pk'")
        assert 'reads=Parameters.of(Parameter("pk", ..., required=True))' in message

    @pytest.mark.parametrize("action", ["update", "partial_update", "destroy"])
    def test_a_write_s_target_selector(self, action: str) -> None:
        viewset = _viewset(action_specs={action: _write(by="other")})
        assert _refusal(viewset, {"put": action}).startswith(
            f"_Notes.{action}: the router captures the lookup as 'pk'"
        )

    def test_a_detail_service_action(self) -> None:
        @service_action(_write(by=None), detail=True, methods=["post"])
        def archive(self: Any, request: Any, pk: Any = None) -> None: ...

        viewset = _viewset(archive=archive)
        assert _refusal(viewset, {"post": "archive"}).startswith(
            "_Notes.archive: the router captures the lookup as 'pk'"
        )

    def test_a_detail_selector_action(self) -> None:
        @selector_action(_row(by=None))
        def peek(self: Any, request: Any, pk: Any = None) -> None: ...

        viewset = _viewset(SelectorViewSet, peek=peek)
        assert _refusal(viewset, {"get": "peek"}).startswith(
            "_Notes.peek: the router captures the lookup as 'pk'"
        )

    def test_a_capture_only_the_write_itself_reads(self) -> None:
        """The kernel hands the target selector its own reads alone."""
        viewset = _viewset(action_specs={"update": _write(by="other", reads=_reads("pk"))})
        assert _refusal(viewset, {"put": "update"}).startswith("_Notes.update:")


class TestTheCaptureName:
    def test_lookup_url_kwarg_is_the_capture(self) -> None:
        viewset = _viewset(lookup_url_kwarg="note_id", action_specs={"update": _write()})
        assert "captures the lookup as 'note_id'" in _refusal(viewset, {"put": "update"})
        _mount(
            _viewset(lookup_url_kwarg="note_id", action_specs={"update": _write(by="note_id")}),
            {"put": "update"},
        )

    def test_lookup_field_is_the_capture_with_no_url_kwarg(self) -> None:
        viewset = _viewset(lookup_field="slug", action_specs={"destroy": _write()})
        assert "captures the lookup as 'slug'" in _refusal(viewset, {"delete": "destroy"})
        _mount(
            _viewset(lookup_field="slug", action_specs={"destroy": _write(by="slug")}),
            {"delete": "destroy"},
        )


class TestWhatIsNotAsked:
    def test_a_target_selector_reading_the_capture_mounts(self) -> None:
        _mount(
            _viewset(action_specs={"update": _write(), "destroy": _write(), "retrieve": _row()}),
            {"get": "retrieve", "put": "update", "delete": "destroy"},
        )

    def test_partial_update_is_asked_of_the_update_spec_it_falls_back_to(self) -> None:
        viewset = _viewset(action_specs={"update": _write(by="other")})
        assert _refusal(viewset, {"patch": "partial_update"}).startswith("_Notes.partial_update:")

    def test_only_the_actions_the_route_maps(self) -> None:
        """The router mounts each route with the actions it maps there."""
        _mount(
            _viewset(action_specs={"retrieve": _row(), "destroy": _write(by="other")}),
            {"get": "retrieve"},
        )

    def test_an_action_no_spec_serves(self) -> None:
        """A DRF handler of the author's has no lookup of this package's."""

        @drf_action(detail=True)
        def peek(self: Any, request: Any, pk: Any = None) -> Response:
            return Response()

        _mount(_viewset(peek=peek), {"get": "peek"})

    def test_a_collection_route(self) -> None:
        """A router mounts the list route and a ``detail=False`` action with ``detail=False``."""

        @service_action(_write(by="other"), methods=["post"])
        def touch(self: Any, request: Any) -> None: ...

        viewset = _viewset(action_specs={"update": _write(by="other")}, touch=touch)
        viewset.as_view({"post": "touch", "put": "update"}, detail=False)

    def test_a_write_over_a_set_or_a_list_body_looks_up_no_row(self) -> None:
        over_a_set = ServiceSpec(
            service=lambda *, collection: None,
            permissions=_OPEN,
            collection_selector_spec=SelectorSpec(
                kind=SelectorKind.LIST, selector=lambda: Author.objects.all()
            ),
        )
        rows = ServiceSpec(
            service=lambda *, data: None,
            permissions=_OPEN,
            validator=SerializerValidator(_NameIn),
            many=True,
        )
        _mount(
            _viewset(action_specs={"update": over_a_set, "destroy": rows}),
            {"put": "update", "delete": "destroy"},
        )

    def test_a_standalone_view(self) -> None:
        """Its capture is the URLconf's, which ``as_view()`` cannot see."""
        type("_View", (SelectorRetrieveView,), {"spec": _row(by=None)}).as_view()


class _Me(serializers.Serializer):
    username = serializers.CharField()


def _me(*, user: Any) -> Any:
    return user


class _MeViewSet(SelectorViewSet):
    """A singleton: the caller's own row, found by who asks, not by a capture."""

    permission_classes: list[Any] = []
    action_specs = {
        "retrieve": SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=_me,
            permissions=_OPEN,
            presenter=SerializerPresenter(_Me),
        )
    }


class TestOnlyARouterMountedDetailRouteIsAsked:
    @pytest.mark.django_db
    def test_a_singleton_mounted_by_hand_serves(self) -> None:
        """``path("me/", MeViewSet.as_view({"get": "retrieve"}))``: no capture on the route."""
        view = _MeViewSet.as_view({"get": "retrieve"})
        request = APIRequestFactory().get("/me/")
        force_authenticate(request, User.objects.create(username="ada"))
        response = view(request)
        response.render()
        assert (response.status_code, response.data) == (200, {"username": "ada"})

    def test_the_same_viewset_on_a_router_is_refused(self) -> None:
        """The router's detail route captures ``pk``, which the selector never reads."""
        router = SimpleRouter()
        router.register("me", _MeViewSet, basename="me")
        with pytest.raises(ImproperlyConfigured) as raised:
            router.urls  # noqa: B018 - building the routes mounts each view
        assert str(raised.value).startswith(
            "_MeViewSet.retrieve: the router captures the lookup as 'pk'"
        )

    def test_the_actions_handed_as_a_keyword(self) -> None:
        with pytest.raises(ImproperlyConfigured):
            _MeViewSet.as_view(actions={"get": "retrieve"}, detail=True)

    def test_no_actions_is_left_to_drf_s_own_refusal(self) -> None:
        with pytest.raises(TypeError, match="actions"):
            _MeViewSet.as_view(detail=True)
