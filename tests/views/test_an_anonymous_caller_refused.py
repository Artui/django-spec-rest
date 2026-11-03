"""A refused caller is answered as DRF's ``APIView.permission_denied`` answers it.

A caller the request's authenticators did not recognise is asked to
authenticate: DRF's ``NotAuthenticated``, which the view answers 401 with the
first authenticator's ``WWW-Authenticate``, or 403 where that authenticator
gives no header. A caller one did recognise, or a request with no
authenticator at all, is refused with the permission's own message, 403.

The rule holds for both kinds of refusal a spec makes: a DRF class adapted by
``DRFPermissionCheck`` answering ``False``, and a kernel ``PermissionCheck``
the kernel's ``dispatch`` refuses with its ``NotPermitted``. Each is served by
a view and by a viewset action, and each answer is DRF's for a plain
``APIView`` guarded by a class carrying the same message.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User
from django_service_specs import PermissionCheck, ServiceSpec
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from django_spec_rest import ServiceCreateView, ServiceViewSet, service_action
from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()

MESSAGE = "Members only."
SIGN_IN = "Authentication credentials were not provided."
CHALLENGE = 'Basic realm="api"'


class _Deny(BasePermission):
    message = MESSAGE

    def has_permission(self, request: Any, view: Any) -> bool:
        return False


class _DenyAll(PermissionCheck):
    message = MESSAGE

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return False


def _spec(refusal: str) -> ServiceSpec:
    check = DRFPermissionCheck([_Deny]) if refusal == "drf-class" else _DenyAll()
    return ServiceSpec(service=lambda: None, permissions=(check,))


def _view(spec: ServiceSpec, authentication: list[type]) -> Any:
    attrs = {"spec": spec, "permission_classes": [], "authentication_classes": authentication}
    return type("_View", (ServiceCreateView,), attrs).as_view()


def _action(spec: ServiceSpec, authentication: list[type]) -> Any:
    class _ViewSet(ServiceViewSet):
        permission_classes = [AllowAny]
        authentication_classes = authentication

        @service_action(spec, detail=False, methods=["post"])
        def ping(self, request: Any) -> None:
            """Stubbed."""

    return _ViewSet.as_view({"post": "ping"})


def _drf_view(spec: ServiceSpec, authentication: list[type]) -> Any:
    """DRF's own answer: a plain view asking ``_Deny`` in ``initial()``."""

    class _Plain(APIView):
        permission_classes = [_Deny]
        authentication_classes = authentication

        def post(self, request: Any) -> Response:
            return Response()

    return _Plain.as_view()


ROUTES = {"view": _view, "viewset-action": _action}
CALLERS = {
    # (authenticators, signed in, the answer)
    "anonymous, a challenge first": (
        [BasicAuthentication, SessionAuthentication],
        False,
        (401, SIGN_IN, CHALLENGE),
    ),
    "anonymous, no challenge first": ([SessionAuthentication], False, (403, SIGN_IN, None)),
    "anonymous, no authenticator": ([], False, (403, MESSAGE, None)),
    "signed in": ([BasicAuthentication], True, (403, MESSAGE, None)),
}


def _answer(view: Any, *, signed_in: bool) -> tuple[int, str, str | None]:
    request = factory.post("/", {}, format="json")
    if signed_in:
        force_authenticate(request, User.objects.create(username="ada"))
    response = view(request)
    response.render()
    return response.status_code, response.data["detail"], response.get("WWW-Authenticate")


@pytest.mark.parametrize("caller", CALLERS)
def test_drf_s_own_view_answers_each_caller_so(caller: str) -> None:
    """The table below is DRF's: its view, asking the same class, answers each row so."""
    authentication, signed_in, expected = CALLERS[caller]
    assert _answer(_drf_view(_spec("drf-class"), authentication), signed_in=signed_in) == expected


def _awaiting_the_edge(refusal: str, caller: str) -> list[Any]:
    """A kernel check's refusal of an anonymous caller needs the request at the map.

    The kernel route's refusal map applies the rule to a kernel denial only
    when the edge hands it the request it served (``answering_refusals``), and
    ``dispatch/kernel_edge.py`` does not hand it yet. Strict, so the line that
    hands it over fails here until these marks come off with it.
    """
    if (
        refusal == "kernel-check"
        and caller.startswith("anonymous")
        and "no authenticator" not in caller
    ):
        return [pytest.mark.xfail(strict=True, reason="the edge hands the map no request yet")]
    return []


CASES = [
    pytest.param(route, refusal, caller, marks=_awaiting_the_edge(refusal, caller))
    for route in ROUTES
    for refusal in ["drf-class", "kernel-check"]
    for caller in CALLERS
]


@pytest.mark.parametrize(("route", "refusal", "caller"), CASES)
def test_a_refused_caller_is_answered_as_drf_answers_it(
    route: str, refusal: str, caller: str
) -> None:
    authentication, signed_in, expected = CALLERS[caller]
    view = ROUTES[route](_spec(refusal), authentication)
    assert _answer(view, signed_in=signed_in) == expected
