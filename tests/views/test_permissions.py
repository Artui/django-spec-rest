"""A kernel spec's ``permissions`` and its view's ``permission_classes`` on the mutation views.

A kernel spec has no ``permission_classes``; its checks are its ``permissions``, which the kernel's
``dispatch`` asks, and the view's own classes are DRF's, asked first. Both
hold, so neither can open what the other closes. DRF's classes reach a spec's
``permissions`` through ``DRFPermissionCheck``. The selector views' cases are
the query views'.
"""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView, ServiceDeleteView, ServiceUpdateView
from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()


class _DenyAll(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return False


class _AuthorIn(serializers.Serializer):
    name = serializers.CharField()


_DENY = (DRFPermissionCheck([_DenyAll]),)
_OPEN = (Unrestricted(),)
_AUTHOR = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
)


def _create_view(permissions: Any, **attrs: Any) -> Any:
    spec = ServiceSpec(
        service=lambda *, data: Author.objects.create(name=data["name"]) and None,
        permissions=permissions,
        validator=SerializerValidator(_AuthorIn),
    )
    return type("_View", (ServiceCreateView,), {"spec": spec, **attrs}).as_view()


def _post(view: Any) -> Any:
    return view(factory.post("/", {"name": "Ada"}, format="json"))


class TestServiceCreateViewPermissions:
    def test_the_spec_s_permission_denies(self) -> None:
        assert _post(_create_view(_DENY)).status_code == 403
        assert not Author.objects.exists()

    def test_the_spec_s_permission_denies_where_the_view_allows(self) -> None:
        assert _post(_create_view(_DENY, permission_classes=[AllowAny])).status_code == 403

    def test_the_view_s_classes_deny_where_the_spec_allows(self) -> None:
        """An open spec does not open a closed view."""
        assert _post(_create_view(_OPEN, permission_classes=[_DenyAll])).status_code == 403
        assert not Author.objects.exists()

    def test_both_open_runs(self) -> None:
        assert _post(_create_view(_OPEN, permission_classes=[AllowAny])).status_code == 204


class TestTargetedViewsPermissions:
    @pytest.mark.parametrize(
        ("base", "method"), [(ServiceUpdateView, "put"), (ServiceDeleteView, "delete")]
    )
    def test_the_spec_s_permission_denies(self, base: type, method: str) -> None:
        author = Author.objects.create(name="Kept")
        ran: list[bool] = []
        spec = ServiceSpec(
            service=lambda *, instance: ran.append(True),
            permissions=_DENY,
            instance_selector_spec=_AUTHOR,
        )
        view = type("_View", (base,), {"spec": spec}).as_view()
        response = view(getattr(factory, method)("/", {}, format="json"), pk=author.pk)
        assert response.status_code == 403
        assert ran == []
