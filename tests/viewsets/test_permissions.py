"""Permissions on a viewset whose actions serve kernel specs.

A kernel spec declares no ``permission_classes``: its checks are its
``permissions``, which the kernel's ``dispatch`` asks after DRF has asked the
view's own classes. So ``get_permissions`` answers the view's classes for a
kernel entry, from ``action_specs`` or stamped on a decorated handler, and the
spec's checks still refuse.
"""

from __future__ import annotations

from typing import Any

import pytest
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
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorViewSet, ServiceViewSet, selector_action, service_action
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _NameIn(serializers.Serializer):
    name = serializers.CharField()


class _Deny(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return False


class _DenyAll(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return False


def _rename(*, instance: Author, data: dict[str, Any]) -> Author:
    instance.name = data["name"]
    instance.save(update_fields=["name"])
    return instance


def _update(**fields: Any) -> ServiceSpec:
    defaults: dict[str, Any] = {
        "service": _rename,
        "permissions": _OPEN,
        "validator": SerializerValidator(_NameIn),
        "presenter": SerializerPresenter(AuthorSerializer),
        "instance_selector_spec": SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
        ),
    }
    return ServiceSpec(**{**defaults, **fields})


def _rows(**fields: Any) -> SelectorSpec:
    defaults: dict[str, Any] = {
        "selector": lambda: Author.objects.order_by("id"),
        "permissions": _OPEN,
        "presenter": SerializerPresenter(AuthorSerializer),
    }
    return SelectorSpec(kind=SelectorKind.LIST, **{**defaults, **fields})


def _call(viewset: Any, method: str, action_name: str, body: Any = None, **kwargs: Any) -> Response:
    request = getattr(factory, method)("/", body, format="json")
    return viewset.as_view({method: action_name})(request, **kwargs)


class TestActionSpecs:
    def test_an_update_entry_s_checks_refuse_a_patch(self) -> None:
        """PATCH falls back to the ``"update"`` entry, checks and all."""
        author = Author.objects.create(name="a")

        class _ViewSet(ServiceViewSet):
            queryset = Author.objects.all()
            action_specs = {"update": _update(permissions=(_DenyAll(),))}

        response = _call(_ViewSet, "patch", "partial_update", {"name": "b"}, pk=author.pk)
        assert response.status_code == 403
        assert Author.objects.get().name == "a"

    def test_a_partial_update_entry_s_checks_win_for_a_patch(self) -> None:
        author = Author.objects.create(name="a")

        class _ViewSet(ServiceViewSet):
            queryset = Author.objects.all()
            action_specs = {
                "update": _update(),
                "partial_update": _update(permissions=(_DenyAll(),)),
            }

        assert _call(_ViewSet, "put", "update", {"name": "b"}, pk=author.pk).status_code == 200
        response = _call(_ViewSet, "patch", "partial_update", {"name": "c"}, pk=author.pk)
        assert response.status_code == 403

    def test_the_view_s_classes_answer_a_kernel_entry(self) -> None:
        class _ViewSet(SelectorViewSet):
            queryset = Author.objects.all()
            permission_classes = [_Deny]
            action_specs = {"list": _rows()}

        assert _call(_ViewSet, "get", "list").status_code == 403


class TestDecoratedActions:
    def test_a_service_action_takes_the_view_s_classes(self) -> None:
        class _ViewSet(ServiceViewSet):
            queryset = Author.objects.all()
            permission_classes = [_Deny]

            @service_action(_update(), detail=True, methods=["post"])
            def rename(self, request: Any, pk: Any = None) -> None:
                """Stubbed."""

        author = Author.objects.create(name="a")
        assert _call(_ViewSet, "post", "rename", {"name": "b"}, pk=author.pk).status_code == 403

    def test_a_service_action_s_own_checks_refuse_on_an_open_view(self) -> None:
        class _ViewSet(ServiceViewSet):
            queryset = Author.objects.all()
            permission_classes = [AllowAny]

            @service_action(_update(permissions=(_DenyAll(),)), detail=True, methods=["post"])
            def rename(self, request: Any, pk: Any = None) -> None:
                """Stubbed."""

        author = Author.objects.create(name="a")
        assert _call(_ViewSet, "post", "rename", {"name": "b"}, pk=author.pk).status_code == 403

    def test_a_selector_action_takes_the_view_s_classes(self) -> None:
        class _ViewSet(SelectorViewSet):
            queryset = Author.objects.all()
            permission_classes = [_Deny]

            @selector_action(_rows())
            def recent(self, request: Any) -> None:
                """Stubbed."""

        assert _call(_ViewSet, "get", "recent").status_code == 403

    def test_a_selector_action_s_own_checks_refuse_on_an_open_view(self) -> None:
        class _ViewSet(SelectorViewSet):
            queryset = Author.objects.all()
            permission_classes = [AllowAny]

            @selector_action(_rows(permissions=(_DenyAll(),)))
            def recent(self, request: Any) -> None:
                """Stubbed."""

        assert _call(_ViewSet, "get", "recent").status_code == 403
