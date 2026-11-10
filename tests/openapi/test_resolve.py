from __future__ import annotations

from typing import Any

from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import (
    SelectorListView,
    ServiceCreateView,
    ServiceViewSet,
    selector_action,
    service_action,
)
from django_spec_rest.openapi._resolve import (
    resolve_discriminated_action,
    resolve_selector_spec,
    resolve_service_spec,
)
from django_spec_rest.types.discriminated_action import DiscriminatedAction

_OPEN = (Unrestricted(),)


def _create(*, data: Any) -> Any: ...


def _list() -> Any: ...


def _get(*, pk: int) -> Any: ...


_create_spec = ServiceSpec(service=_create, permissions=_OPEN)
_list_spec = SelectorSpec(kind=SelectorKind.LIST, selector=_list, permissions=_OPEN)
_retrieve_spec = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=_get,
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
    permissions=_OPEN,
)


class _StandaloneView(ServiceCreateView):
    spec = _create_spec


class _StandaloneListView(SelectorListView):
    spec = _list_spec


_wrapper = DiscriminatedAction(lambda: "only", {"only": _create_spec})


class _ViewSet(ServiceViewSet):
    action_specs = {
        "create": _create_spec,
        "list": _list_spec,
        "retrieve": _retrieve_spec,
        "update": _wrapper,
    }


class _ActionViewSet(GenericViewSet):
    @service_action(_create_spec, detail=False, methods=["post"])
    def go(self, request: Any) -> Any: ...

    @selector_action(_list_spec, detail=False)
    def recent(self, request: Any) -> Any: ...

    @service_action(_wrapper, detail=False, methods=["post"])
    def either(self, request: Any) -> Any: ...


class _WrapperView(ServiceCreateView):
    """Refused by ``as_view()``, but the walk reads its ``spec`` as it reads any."""

    spec = _wrapper


def _bound(view_cls: type, action: str) -> Any:
    instance = view_cls()
    instance.action = action
    return instance


class TestResolveServiceSpec:
    def test_a_standalone_view_s_spec(self) -> None:
        assert resolve_service_spec(_StandaloneView()) is _create_spec

    def test_an_action_specs_entry(self) -> None:
        assert resolve_service_spec(_bound(_ViewSet, "create")) is _create_spec

    def test_a_service_action_s_stamp(self) -> None:
        assert resolve_service_spec(_bound(_ActionViewSet, "go")) is _create_spec

    def test_a_selector_entry_is_none(self) -> None:
        assert resolve_service_spec(_bound(_ViewSet, "list")) is None
        assert resolve_service_spec(_StandaloneListView()) is None


class TestResolveSelectorSpec:
    def test_a_standalone_view_s_spec(self) -> None:
        assert resolve_selector_spec(_StandaloneListView()) is _list_spec

    def test_an_action_specs_entry(self) -> None:
        assert resolve_selector_spec(_bound(_ViewSet, "retrieve")) is _retrieve_spec

    def test_a_selector_action_s_stamp(self) -> None:
        assert resolve_selector_spec(_bound(_ActionViewSet, "recent")) is _list_spec

    def test_a_service_entry_is_none(self) -> None:
        assert resolve_selector_spec(_bound(_ViewSet, "create")) is None
        assert resolve_selector_spec(_StandaloneView()) is None

    def test_a_viewset_with_no_action_specs_and_no_stamp_is_none(self) -> None:
        """``_ActionViewSet`` declares no ``action_specs``."""
        assert resolve_selector_spec(_bound(_ActionViewSet, "go")) is None


class TestResolveDiscriminatedAction:
    def test_an_action_specs_entry(self) -> None:
        assert resolve_discriminated_action(_bound(_ViewSet, "update")) is _wrapper

    def test_a_service_action_s_stamp(self) -> None:
        assert resolve_discriminated_action(_bound(_ActionViewSet, "either")) is _wrapper

    def test_a_view_s_spec(self) -> None:
        assert resolve_discriminated_action(_WrapperView()) is _wrapper

    def test_a_plain_spec_is_none(self) -> None:
        assert resolve_discriminated_action(_bound(_ViewSet, "create")) is None
        assert resolve_discriminated_action(_bound(_ActionViewSet, "go")) is None
        assert resolve_discriminated_action(_StandaloneView()) is None

    def test_a_view_with_no_action_is_none(self) -> None:
        assert resolve_discriminated_action(_ViewSet()) is None

    def test_it_is_no_service_spec_and_no_selector_spec(self) -> None:
        # The wrapper is not a kernel spec: each of the other resolvers leaves it to this one.
        for view in (_bound(_ViewSet, "update"), _bound(_ActionViewSet, "either"), _WrapperView()):
            assert resolve_service_spec(view) is None
            assert resolve_selector_spec(view) is None
