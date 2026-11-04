"""The 403 and 401 a spec's permission checks are refused with, against what the edge sends.

A spec declaring any check but ``Unrestricted`` documents a 403: a check's
denial and a principal who cannot act are both answered 403 with a ``detail``.
Any such check refusing a caller nobody authenticated, a kernel check or a
``DRFPermissionCheck``, is answered 401 where the view's first authenticator
sends a challenge, so such an operation documents the 401 too. Each test that drives a view validates the wire body
against the schema the operation documents for the status it was answered.
"""

from __future__ import annotations

import json
from typing import Any

import jsonschema
import pytest
from django.contrib.auth.models import User
from django.urls import path
from django_service_specs import (
    AllOf,
    AnyOf,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from drf_spectacular.generators import SchemaGenerator
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest import SelectorListView, ServiceCreateView
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck

MESSAGE = "Members only."


class _Deny(BasePermission):
    message = MESSAGE

    def has_permission(self, request: Any, view: Any) -> bool:
        return False


class _DenyAll(PermissionCheck):
    message = MESSAGE

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return False


class _Admit(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True


def _write(*checks: PermissionCheck) -> ServiceSpec:
    return ServiceSpec(service=lambda: None, permissions=checks)


def _read(*checks: PermissionCheck) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.LIST, selector=lambda: [], permissions=checks)


_BASIC = [BasicAuthentication]
_SESSION_FIRST = [SessionAuthentication, BasicAuthentication]

# key: (view class, spec, authentication classes)
_ROUTES: dict[str, tuple[type, Any, list[type]]] = {
    "unrestricted": (ServiceCreateView, _write(Unrestricted()), _BASIC),
    "unrestricted-read": (SelectorListView, _read(Unrestricted()), _BASIC),
    "kernel": (ServiceCreateView, _write(_DenyAll()), []),
    "kernel-challenged": (ServiceCreateView, _write(_DenyAll()), _BASIC),
    "kernel-read": (SelectorListView, _read(_DenyAll()), []),
    "kernel-read-challenged": (SelectorListView, _read(_DenyAll()), _BASIC),
    "kernel-session": (ServiceCreateView, _write(_DenyAll()), _SESSION_FIRST),
    "admitting": (ServiceCreateView, _write(_Admit()), []),
    "drf-session": (ServiceCreateView, _write(DRFPermissionCheck([_Deny])), _SESSION_FIRST),
    "drf-basic": (ServiceCreateView, _write(DRFPermissionCheck([_Deny])), _BASIC),
    "drf-basic-read": (SelectorListView, _read(DRFPermissionCheck([_Deny])), _BASIC),
    "drf-none": (ServiceCreateView, _write(DRFPermissionCheck([_Deny])), []),
    "drf-all-of": (
        ServiceCreateView,
        _write(AllOf(_Admit(), DRFPermissionCheck([_Deny]))),
        _BASIC,
    ),
    "drf-any-of": (
        ServiceCreateView,
        _write(AnyOf(_DenyAll(), DRFPermissionCheck([_Deny]))),
        _BASIC,
    ),
    "drf-nested": (
        ServiceCreateView,
        _write(AllOf(_Admit(), AnyOf(_DenyAll(), DRFPermissionCheck([_Deny])))),
        _BASIC,
    ),
    "kernel-combined": (ServiceCreateView, _write(AnyOf(_DenyAll(), _Admit())), _BASIC),
}

urlpatterns = [
    path(
        f"{key}/",
        type(
            "_View",
            (view,),
            {"spec": spec, "permission_classes": [], "authentication_classes": authentication},
        ).as_view(),
    )
    for key, (view, spec, authentication) in _ROUTES.items()
]


@pytest.fixture(scope="module", autouse=True)
def _enable_openapi() -> None:
    enable_openapi()


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)


def _method(key: str) -> str:
    return "get" if _ROUTES[key][0] is SelectorListView else "post"


def _responses(schema: dict[str, Any], key: str) -> dict[str, Any]:
    return schema["paths"][f"/{key}/"][_method(key)]["responses"]


def _documented(schema: dict[str, Any], key: str, status: int) -> dict[str, Any]:
    body = _responses(schema, key)[str(status)]["content"]["application/json"]["schema"]
    return {**body, "components": schema["components"]}


def _call(key: str, user: Any = None) -> tuple[int, Any, Any]:
    view = urlpatterns[list(_ROUTES).index(key)].callback
    method = _method(key)
    request = getattr(APIRequestFactory(), method)("/", {}, format="json")
    if user is not None:
        force_authenticate(request, user)
    response = view(request)
    response.render()
    body = json.loads(response.content) if response.content else None
    return response.status_code, body, response.get("WWW-Authenticate")


class TestTheSchema:
    @pytest.mark.parametrize("key", ["unrestricted", "unrestricted-read"])
    def test_an_unrestricted_spec_documents_no_403(self, schema: dict[str, Any], key: str) -> None:
        assert {"401", "403"}.isdisjoint(_responses(schema, key))

    @pytest.mark.parametrize("key", ["kernel", "kernel-read", "admitting", "drf-session"])
    def test_a_checked_spec_documents_a_403(self, schema: dict[str, Any], key: str) -> None:
        assert "403" in _responses(schema, key)

    def test_the_403_is_the_permission_denied_component(self, schema: dict[str, Any]) -> None:
        response = _responses(schema, "kernel")["403"]
        assert response["description"] == "The caller may not run this operation."
        assert response["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/PermissionDenied"
        }
        assert schema["components"]["schemas"]["PermissionDenied"]["required"] == ["detail"]

    @pytest.mark.parametrize("key", ["drf-session", "kernel-session"])
    def test_a_check_behind_a_session_documents_no_401(
        self, schema: dict[str, Any], key: str
    ) -> None:
        assert "401" not in _responses(schema, key)
        assert "403" in _responses(schema, key)

    @pytest.mark.parametrize("key", ["drf-none", "kernel"])
    def test_a_check_behind_no_authenticator_documents_no_401(
        self, schema: dict[str, Any], key: str
    ) -> None:
        assert "401" not in _responses(schema, key)

    @pytest.mark.parametrize(
        "key",
        ["drf-basic", "drf-basic-read", "kernel-challenged", "kernel-read-challenged"],
    )
    def test_a_check_behind_a_challenge_documents_a_401(
        self, schema: dict[str, Any], key: str
    ) -> None:
        response = _responses(schema, key)["401"]
        assert response["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/NotAuthenticated"
        }

    @pytest.mark.parametrize("key", ["drf-all-of", "drf-any-of", "drf-nested", "kernel-combined"])
    def test_a_check_inside_a_combinator_documents_its_401(
        self, schema: dict[str, Any], key: str
    ) -> None:
        assert "401" in _responses(schema, key)


@pytest.mark.django_db
class TestTheWire:
    """Each refusal driven through its view, its body validated against the documented one."""

    @pytest.mark.parametrize(
        ("key", "signed_in"),
        [
            # A kernel check's denial on a view with no authenticator.
            ("kernel", False),
            ("kernel-read", False),
            # An adapted DRF class refusing a signed-in caller.
            ("drf-basic", True),
            ("drf-basic-read", True),
            # An adapted DRF class refusing a caller nobody authenticated,
            # behind an authenticator sending no challenge.
            ("drf-session", False),
            # An adapted DRF class on a view with no authenticator.
            ("drf-none", False),
            # A kernel check refusing a caller nobody authenticated, behind an
            # authenticator sending no challenge.
            ("kernel-session", False),
            # A kernel check refusing a signed-in caller behind a challenge.
            ("kernel-challenged", True),
            ("kernel-read-challenged", True),
        ],
    )
    def test_each_403_the_edge_sends_is_the_documented_body(
        self, schema: dict[str, Any], key: str, signed_in: bool
    ) -> None:
        user = User.objects.create(username="member") if signed_in else None
        status, body, _ = _call(key, user)
        assert status == 403
        jsonschema.validate(body, _documented(schema, key, 403))

    @pytest.mark.parametrize("key", ["admitting", "kernel"])
    def test_a_principal_who_cannot_act_is_the_documented_403(
        self, schema: dict[str, Any], key: str
    ) -> None:
        status, body, _ = _call(key, User.objects.create(username="gone", is_active=False))
        assert status == 403
        assert body == {"detail": "The acting principal is unavailable."}
        jsonschema.validate(body, _documented(schema, key, 403))

    @pytest.mark.parametrize(
        "key",
        [
            "drf-basic",
            "drf-basic-read",
            "drf-any-of",
            "kernel-challenged",
            "kernel-read-challenged",
        ],
    )
    def test_the_401_the_edge_sends_is_the_documented_body(
        self, schema: dict[str, Any], key: str
    ) -> None:
        status, body, challenge = _call(key)
        assert (status, challenge) == (401, 'Basic realm="api"')
        jsonschema.validate(body, _documented(schema, key, 401))

    def test_an_unrestricted_spec_is_not_refused(self, schema: dict[str, Any]) -> None:
        status, _, _ = _call("unrestricted")
        assert status == 204
