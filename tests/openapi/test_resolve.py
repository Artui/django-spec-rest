"""The schema's spec resolvers answer a kernel spec on every surface that serves one.

A standalone view's ``spec``, an ``action_specs`` entry and the stamp
``@service_action`` / ``@selector_action`` leave on their handler each carry
the kernel's own ``ServiceSpec`` or ``SelectorSpec``; each test fails against
resolvers that recognise only drfs specs, which answer ``None`` for all three.
"""

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
from django_spec_rest.openapi._resolve import resolve_selector_spec, resolve_service_spec

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


class _ViewSet(ServiceViewSet):
    action_specs = {"create": _create_spec, "list": _list_spec, "retrieve": _retrieve_spec}


class _ActionViewSet(GenericViewSet):
    @service_action(_create_spec, detail=False, methods=["post"])
    def go(self, request: Any) -> Any: ...

    @selector_action(_list_spec, detail=False)
    def recent(self, request: Any) -> Any: ...


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
