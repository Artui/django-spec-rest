"""A refused caller is answered as DRF's ``APIView.permission_denied`` answers it.

A caller the request's authenticators did not recognise is asked to
authenticate: DRF's ``NotAuthenticated``, which the view answers 401 with the
first authenticator's ``WWW-Authenticate``, or 403 where that authenticator
gives no header. A caller one did recognise, or a request with no
authenticator at all, is refused with the permission's own message, 403.

The rule holds for a DRF class adapted by ``DRFPermissionCheck`` answering
``False``. A kernel ``PermissionCheck`` the kernel's ``dispatch`` refuses with
its ``NotPermitted`` is still the kernel's 403 with its message: the kernel
raises a bare ``NotPermitted``, which the edge cannot tell from a service's own
or a refused inner dispatch's, so those cases are strict xfails until the kernel
marks a permission check's denial and this route keys the 401 on the mark. Each
route is served by a view and by a viewset action, and each answer is DRF's for
a plain ``APIView`` guarded by a class carrying the same message.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User
from django_service_specs import (
    NotPermitted,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    dispatch,
)
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from django_spec_rest import (
    SelectorListView,
    SelectorViewSet,
    ServiceCreateView,
    ServiceViewSet,
    selector_action,
    service_action,
)
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


def _check(refusal: str) -> PermissionCheck:
    return DRFPermissionCheck([_Deny]) if refusal == "drf-class" else _DenyAll()


def _write(check: PermissionCheck) -> ServiceSpec:
    return ServiceSpec(service=lambda: None, permissions=(check,))


def _read(check: PermissionCheck) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.LIST, selector=lambda: [], permissions=(check,))


def _view(check: PermissionCheck, authentication: list[type]) -> Any:
    attrs = {
        "spec": _write(check),
        "permission_classes": [],
        "authentication_classes": authentication,
    }
    return type("_View", (ServiceCreateView,), attrs).as_view()


def _list_view(check: PermissionCheck, authentication: list[type]) -> Any:
    attrs = {
        "spec": _read(check),
        "permission_classes": [],
        "authentication_classes": authentication,
    }
    return type("_View", (SelectorListView,), attrs).as_view()


def _action(check: PermissionCheck, authentication: list[type]) -> Any:
    class _ViewSet(ServiceViewSet):
        permission_classes = [AllowAny]
        authentication_classes = authentication

        @service_action(_write(check), detail=False, methods=["post"])
        def ping(self, request: Any) -> None:
            """Stubbed."""

    return _ViewSet.as_view({"post": "ping"})


def _read_action(check: PermissionCheck, authentication: list[type]) -> Any:
    class _ViewSet(SelectorViewSet):
        permission_classes = [AllowAny]
        authentication_classes = authentication

        @selector_action(_read(check))
        def recent(self, request: Any) -> None:
            """Stubbed."""

    return _ViewSet.as_view({"get": "recent"})


def _drf_view(authentication: list[type]) -> Any:
    """DRF's own answer: a plain view asking ``_Deny`` in ``initial()``."""

    class _Plain(APIView):
        permission_classes = [_Deny]
        authentication_classes = authentication

        def post(self, request: Any) -> Response:
            return Response()

    return _Plain.as_view()


ROUTES = {
    "view": (_view, "post"),
    "list-view": (_list_view, "get"),
    "viewset-action": (_action, "post"),
    "selector-action": (_read_action, "get"),
}
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


def _answer(view: Any, *, signed_in: bool, method: str = "post") -> tuple[int, str, str | None]:
    request = getattr(factory, method)("/", {}, format="json")
    if signed_in:
        force_authenticate(request, User.objects.create(username="ada"))
    response = view(request)
    response.render()
    return response.status_code, response.data["detail"], response.get("WWW-Authenticate")


@pytest.mark.parametrize("caller", CALLERS)
def test_drf_s_own_view_answers_each_caller_so(caller: str) -> None:
    """The table below is DRF's: its view, asking the same class, answers each row so."""
    authentication, signed_in, expected = CALLERS[caller]
    assert _answer(_drf_view(authentication), signed_in=signed_in) == expected


def _awaiting_the_kernel(refusal: str, caller: str) -> list[Any]:
    """A kernel check's refusal of an anonymous caller is not asked to sign in yet.

    The kernel raises a bare ``NotPermitted`` for a permission check's denial,
    the same class a service raises of its own accord or a refused inner
    dispatch raises, so the edge cannot ask only the first to authenticate
    (``test_a_service_s_own_denial_is_not_asked_to_sign_in`` holds the others).
    Strict, so the marks come off with the kernel's mark and this route's key on it.
    """
    if refusal == "kernel-check" and CALLERS[caller][0] and not CALLERS[caller][1]:
        return [
            pytest.mark.xfail(
                strict=True,
                reason="the kernel does not mark a permission check's denial apart "
                "from any other NotPermitted",
            )
        ]
    return []


CASES = [
    pytest.param(route, refusal, caller, marks=_awaiting_the_kernel(refusal, caller))
    for route in ROUTES
    for refusal in ["drf-class", "kernel-check"]
    for caller in CALLERS
]


@pytest.mark.parametrize(("route", "refusal", "caller"), CASES)
def test_a_refused_caller_is_answered_as_drf_answers_it(
    route: str, refusal: str, caller: str
) -> None:
    authentication, signed_in, expected = CALLERS[caller]
    build, method = ROUTES[route]
    view = build(_check(refusal), authentication)
    assert _answer(view, signed_in=signed_in, method=method) == expected


class _Open(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True


def _anonymous_post(spec: ServiceSpec) -> Any:
    """An anonymous caller of a view with ``BasicAuthentication`` first, which would challenge."""
    view = _view_of(spec, [BasicAuthentication])
    return view(factory.post("/", {}, format="json"))


def _view_of(spec: ServiceSpec, authentication: list[type]) -> Any:
    attrs = {"spec": spec, "permission_classes": [], "authentication_classes": authentication}
    return type("_View", (ServiceCreateView,), attrs).as_view()


def test_a_service_s_own_denial_is_not_asked_to_sign_in() -> None:
    """The author's ``NotPermitted`` is no permission check refusing: 403 with their message.

    Fails when the edge hands the refusal map the request: every kernel
    ``NotPermitted`` is then read as a permission check's and answered 401.
    """

    def archived() -> None:
        raise NotPermitted("Archived invoices are read-only.")

    response = _anonymous_post(ServiceSpec(service=archived, permissions=(_Open(),)))
    assert response.status_code == 403
    assert response.data == {"detail": "Archived invoices are read-only."}
    assert response.get("WWW-Authenticate") is None


def test_a_refused_inner_dispatch_is_not_asked_to_sign_in() -> None:
    """An inner ``dispatch`` its check refuses reaches the caller as that check's 403.

    The caller reached the outer spec through its own check, so the inner's
    refusal is the service's, not a request to authenticate.
    """

    class Never(PermissionCheck):
        message = "Inner refused."

        def has_permission(self, principal: Any, spec: Any) -> bool:
            return False

    inner = ServiceSpec(service=lambda: None, permissions=(Never(),))

    def outer() -> None:
        dispatch(inner, principal=None, arguments={})

    response = _anonymous_post(ServiceSpec(service=outer, permissions=(_Open(),)))
    assert response.status_code == 403
    assert response.data == {"detail": "Inner refused."}
    assert response.get("WWW-Authenticate") is None
