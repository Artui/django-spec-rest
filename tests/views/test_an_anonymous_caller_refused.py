"""A refused caller is answered as DRF's ``APIView.permission_denied`` answers it.

A caller the request's authenticators did not recognise is asked to
authenticate: DRF's ``NotAuthenticated``, which the view answers 401 with the
first authenticator's ``WWW-Authenticate``, or 403 where that authenticator
gives no header. A caller one did recognise, or a request with no
authenticator at all, is refused with the permission's own message, 403.

The rule holds for a DRF class adapted by ``DRFPermissionCheck`` answering
``False``, and for a kernel ``PermissionCheck`` the dispatched spec declares,
whose denial the kernel marks as ``PermissionCheckDenied``: at the class-level
check, and at the object-level one asked of the row the spec's own lookup
finds. Any other ``NotPermitted`` - a service's own, a refused inner
dispatch's, a check's own raise rather than its ``False`` - is not the
caller's to sign in for, and stays 403 with its message. Each route is served
by a view and by a viewset action, and each answer is DRF's for a plain
``APIView`` guarded by a class carrying the same message.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User
from django_service_specs import (
    NotPermitted,
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    dispatch,
)
from rest_framework import serializers
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from django_spec_rest import (
    SelectorListView,
    SelectorViewSet,
    ServiceCreateView,
    ServiceUpdateView,
    ServiceViewSet,
    selector_action,
    service_action,
)
from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author

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


@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("refusal", ["drf-class", "kernel-check"])
@pytest.mark.parametrize("route", ROUTES)
def test_a_refused_caller_is_answered_as_drf_answers_it(
    route: str, refusal: str, caller: str
) -> None:
    authentication, signed_in, expected = CALLERS[caller]
    build, method = ROUTES[route]
    view = build(_check(refusal), authentication)
    assert _answer(view, signed_in=signed_in, method=method) == expected


class _Note(serializers.Serializer):
    note = serializers.CharField(required=False)


def _supplied() -> dict[str, Any]:
    return {"note": "server"}


TWINS = {
    # A form body: the edge dispatches a lenient twin of the spec's Validator.
    "a form body": ({}, "multipart"),
    # An ``input_data`` provider beside a serializer: the edge dispatches a
    # twin recording the provider's answer.
    "an input_data provider": ({"input_data": _supplied}, "json"),
}


@pytest.mark.parametrize("twin", TWINS)
@pytest.mark.parametrize("caller", CALLERS)
def test_a_check_s_denial_of_a_twin_the_edge_dispatched_asks_to_sign_in(
    twin: str, caller: str
) -> None:
    """The kernel names the spec it was handed (the twin), so that spec's denial is the call's own.

    Fails where the edge compares the denial's spec with the view's
    declaration: the twin is another object, and its check's denial of an
    anonymous caller would be read as an inner dispatch's, 403.
    """
    seats, body_format = TWINS[twin]
    authentication, signed_in, expected = CALLERS[caller]
    spec = ServiceSpec(
        service=lambda: None,
        permissions=(_DenyAll(),),
        validator=SerializerValidator(_Note),
        **seats,
    )
    request = factory.post("/", {"note": "x"}, format=body_format)
    if signed_in:
        force_authenticate(request, User.objects.create(username="ada"))
    response = _view_of(spec, authentication)(request)
    response.render()
    assert (
        response.status_code,
        response.data["detail"],
        response.get("WWW-Authenticate"),
    ) == expected


class _NotThisRow(PermissionCheck):
    """Lets every caller reach the spec, and refuses each the row it finds."""

    message = MESSAGE

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True

    def has_object_permission(self, principal: Any, spec: Any, obj: Any) -> bool:
        return False


def _author(*, pk: int) -> Author | None:
    return Author.objects.filter(pk=pk).first()


@pytest.mark.parametrize("caller", CALLERS)
def test_an_object_level_check_s_denial_is_answered_as_drf_answers_it(caller: str) -> None:
    """The row the spec's lookup finds is checked in the edge too, refused as the class check is.

    DRF's ``check_object_permissions`` answers through the same
    ``permission_denied``, so a caller nobody authenticated is asked to.
    """
    authentication, signed_in, expected = CALLERS[caller]
    spec = ServiceSpec(
        service=lambda *, instance: None,
        permissions=(_NotThisRow(),),
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=_author,
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
        ),
    )
    attrs = {"spec": spec, "permission_classes": [], "authentication_classes": authentication}
    view = type("_View", (ServiceUpdateView,), attrs).as_view()
    author = Author.objects.create(name="Ada")
    request = factory.put("/", {}, format="json")
    if signed_in:
        force_authenticate(request, User.objects.create(username="ada"))
    response = view(request, pk=author.pk)
    response.render()
    assert (
        response.status_code,
        response.data["detail"],
        response.get("WWW-Authenticate"),
    ) == expected


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

    Fails when the map's row for a check's denial is widened to every kernel
    ``NotPermitted``: the author's is then read as a check's and answered 401.
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
    refusal is the service's, not a request to authenticate. The kernel marks
    the inner check's denial as it marks the outer's, so this fails when the
    edge answers every ``PermissionCheckDenied`` as its own call's, rather than
    only one naming the spec it dispatched.
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


class _RaisesNotPermitted(PermissionCheck):
    """A check that refuses by raising, rather than by answering ``False``."""

    def has_permission(self, principal: Any, spec: Any) -> bool:
        raise NotPermitted("Members only, raised.")


def test_a_check_raising_not_permitted_is_answered_as_raised() -> None:
    """The kernel marks only a check answering ``False`` as a denial; a raise is the check's word.

    An anonymous caller behind a challenge is answered 403 with the raised
    message and no challenge, as DRF answers a permission class that raises
    ``PermissionDenied``. Fails when the map's row for a bare kernel
    ``NotPermitted`` is routed through ``permission_denied``: the raise is then
    read as a denial and answered 401 with the challenge.
    """
    response = _anonymous_post(
        ServiceSpec(service=lambda: None, permissions=(_RaisesNotPermitted(),))
    )
    response.render()
    assert response.status_code == 403
    assert response.data == {"detail": "Members only, raised."}
    assert response.get("WWW-Authenticate") is None
