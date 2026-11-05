"""A caller the spec's checks refuse is refused before the body's shape is checked.

DRF asks a view's permission classes in ``initial()``, before the handler reads
the body, and drfs asked them there. The kernel's ``dispatch`` checks the
arguments' shape first and asks the spec's checks second, so the edge asks the
checks first itself (``_admitted`` in ``dispatch/kernel_edge.py``): a
caller the checks refuse is answered 401 or 403 whatever the body, as for a
well-formed one, and an admitted caller is told what its body lacks.

A body that fails its shape has no checked arguments to show a check, so the
checks are judged on none, as the OPTIONS answer judges whether to describe a
method. A check that cannot answer without the arguments, raising on their
absence, keeps the kernel's order: the shape's 400 is told, and the check is
asked once the shape passes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django_service_specs import (
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
)
from rest_framework import serializers
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest import (
    SelectorListView,
    ServiceCreateView,
    ServiceUpdateView,
    ServiceViewSet,
    service_action,
)
from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()

EDITORS_ONLY = "Editors only."
SIGN_IN = "Authentication credentials were not provided."
CHALLENGE = 'Basic realm="api"'


class _IsEditor(BasePermission):
    message = EDITORS_ONLY

    def has_permission(self, request: Any, view: Any) -> bool:
        return bool(request.user and request.user.username == "editor")


class _EditorCheck(PermissionCheck):
    """The same rule as a kernel check, answering ``False`` to everyone else."""

    message = EDITORS_ONLY

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return getattr(principal, "username", None) == "editor"


class _Review(serializers.Serializer):
    submission_id = serializers.IntegerField()
    outcome = serializers.CharField()


def _check(refusal: str) -> PermissionCheck:
    return DRFPermissionCheck([_IsEditor]) if refusal == "drf-class" else _EditorCheck()


def _spec(check: PermissionCheck) -> ServiceSpec:
    return ServiceSpec(
        service=lambda *, submission_id, outcome: None,
        permissions=(check,),
        validator=SerializerValidator(_Review),
    )


def _view(check: PermissionCheck, authentication: list[type]) -> Any:
    attrs = {
        "spec": _spec(check),
        "permission_classes": [],
        "authentication_classes": authentication,
    }
    return type("_View", (ServiceCreateView,), attrs).as_view()


def _action(check: PermissionCheck, authentication: list[type]) -> Any:
    class _ViewSet(ServiceViewSet):
        permission_classes = [AllowAny]
        authentication_classes = authentication

        @service_action(_spec(check), detail=False, methods=["post"])
        def review(self, request: Any) -> None:
            """Stubbed."""

    return _ViewSet.as_view({"post": "review"})


ROUTES = {"view": _view, "viewset-action": _action}
REFUSALS = ["drf-class", "kernel-check"]
BODIES = {
    "empty": {},
    "one field missing": {"submission_id": 7},
    "a field of the wrong type": {"submission_id": "x", "outcome": "accept"},
}
REFUSED = {
    # (authenticators, who signs in, the answer)
    "anonymous, a challenge first": (
        [BasicAuthentication, SessionAuthentication],
        None,
        (401, SIGN_IN, CHALLENGE),
    ),
    "anonymous, no challenge first": ([SessionAuthentication], None, (403, SIGN_IN, None)),
    "signed in, not an editor": ([BasicAuthentication], "ada", (403, EDITORS_ONLY, None)),
}


def _post(view: Any, body: Any, *, username: str | None) -> Any:
    request = factory.post("/", body, format="json")
    if username is not None:
        force_authenticate(request, User.objects.create(username=username))
    response = view(request)
    response.render()
    return response


def _answer(response: Any) -> tuple[int, Any, str | None]:
    return (
        response.status_code,
        response.data.get("detail"),
        response.get("WWW-Authenticate"),
    )


@pytest.mark.parametrize("body", BODIES)
@pytest.mark.parametrize("caller", REFUSED)
@pytest.mark.parametrize("refusal", REFUSALS)
@pytest.mark.parametrize("route", ROUTES)
def test_a_refused_caller_is_refused_whatever_the_body(
    route: str, refusal: str, caller: str, body: str
) -> None:
    """Anonymous: 401 or 403 asking to sign in; signed in and refused: the check's 403.

    Fails where the edge leaves the checks to the kernel's order: each body
    here fails its shape, so the caller was answered 400 with the field errors.
    """
    authentication, username, expected = REFUSED[caller]
    view = ROUTES[route](_check(refusal), authentication)
    assert _answer(_post(view, BODIES[body], username=username)) == expected


@pytest.mark.parametrize("caller", REFUSED)
@pytest.mark.parametrize("refusal", REFUSALS)
def test_a_refused_caller_sending_a_complete_body_is_answered_the_same(
    refusal: str, caller: str
) -> None:
    """The answer a refused caller gets for a well-formed body, which the table above matches."""
    authentication, username, expected = REFUSED[caller]
    view = _view(_check(refusal), authentication)
    body = {"submission_id": 7, "outcome": "accept"}
    assert _answer(_post(view, body, username=username)) == expected


@pytest.mark.parametrize("refusal", REFUSALS)
@pytest.mark.parametrize("route", ROUTES)
def test_an_admitted_caller_is_told_what_its_body_lacks(route: str, refusal: str) -> None:
    view = ROUTES[route](_check(refusal), [BasicAuthentication])
    response = _post(view, {}, username="editor")
    assert response.status_code == 400
    assert set(response.data) == {"submission_id", "outcome"}


@pytest.mark.parametrize("refusal", REFUSALS)
def test_an_admitted_caller_s_complete_body_runs(refusal: str) -> None:
    view = _view(_check(refusal), [BasicAuthentication])
    response = _post(view, {"submission_id": 7, "outcome": "accept"}, username="editor")
    assert response.status_code == 204


class _Counting(PermissionCheck):
    def __init__(self) -> None:
        self.asked = 0

    def has_permission(self, principal: Any, spec: Any) -> bool:
        self.asked += 1
        return True


def test_a_well_formed_call_asks_the_class_level_check_once() -> None:
    """The prelude's grant reaches ``dispatch``, which honours it rather than asking again."""
    check = _Counting()
    view = _view(check, [BasicAuthentication])
    response = _post(view, {"submission_id": 7, "outcome": "accept"}, username="ada")
    assert response.status_code == 204
    assert check.asked == 1


class _Name(serializers.Serializer):
    name = serializers.CharField()


def test_a_row_write_asks_the_class_level_check_once() -> None:
    """Handed on to the target's lookup too, which the view asks its object permissions of."""
    check = _Counting()
    spec = ServiceSpec(
        service=lambda *, instance, name: None,
        permissions=(check,),
        validator=SerializerValidator(_Name),
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
        ),
    )
    attrs = {"spec": spec, "permission_classes": [], "authentication_classes": []}
    view = type("_View", (ServiceUpdateView,), attrs).as_view()
    author = Author.objects.create(name="Ada")
    response = view(factory.put("/", {"name": "Grace"}, format="json"), pk=author.pk)
    assert response.status_code == 204
    assert check.asked == 1


class _OwnerOnly(PermissionCheck):
    """A check that reads the call's arguments, and cannot answer without them."""

    message = "Not your submission."

    def has_permission(
        self, principal: Any, spec: Any, *, arguments: Mapping[str, Any] | None = None
    ) -> bool:
        return arguments["submission_id"] == 7  # ty: ignore[not-subscriptable]


def _owner_view() -> Any:
    attrs = {
        "spec": _spec(_OwnerOnly()),
        "permission_classes": [],
        "authentication_classes": [BasicAuthentication],
    }
    return type("_View", (ServiceCreateView,), attrs).as_view()


def test_a_check_reading_the_arguments_keeps_the_kernel_s_order() -> None:
    """It cannot be judged on no arguments, so the shape's refusal is told first.

    Fails where a check raising on the absent arguments is read as a refusal:
    the caller would be told 403 for a body it has not finished.
    """
    response = _post(_owner_view(), {}, username="ada")
    assert response.status_code == 400
    assert set(response.data) == {"submission_id", "outcome"}


def test_a_check_reading_the_arguments_judges_a_well_formed_body() -> None:
    view = _owner_view()
    refused = _post(view, {"submission_id": 8, "outcome": "accept"}, username="ada")
    admitted = _post(view, {"submission_id": 7, "outcome": "accept"}, username="grace")
    assert (refused.status_code, refused.data["detail"]) == (403, "Not your submission.")
    assert admitted.status_code == 204


def _list_view(authentication: list[type]) -> Any:
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda *, year: [],
        permissions=(DRFPermissionCheck([_IsEditor]),),
        reads=Parameters.of(Parameter("year", "integer", required=True)),
    )
    attrs = {"spec": spec, "permission_classes": [], "authentication_classes": authentication}
    return type("_View", (SelectorListView,), attrs).as_view()


@pytest.mark.parametrize("query", [{}, {"year": "x"}])
@pytest.mark.parametrize("caller", REFUSED)
def test_a_read_s_refused_caller_is_refused_whatever_the_query_string(
    caller: str, query: dict[str, str]
) -> None:
    authentication, username, expected = REFUSED[caller]
    request = factory.get("/", query)
    if username is not None:
        force_authenticate(request, User.objects.create(username=username))
    response = _list_view(authentication)(request)
    response.render()
    assert _answer(response) == expected


def test_a_read_s_admitted_caller_is_told_what_its_query_string_lacks() -> None:
    request = factory.get("/", {"year": "x"})
    force_authenticate(request, User.objects.create(username="editor"))
    response = _list_view([BasicAuthentication])(request)
    assert response.status_code == 400
    assert set(response.data) == {"year"}


class _ArgumentsOnly(PermissionCheck):
    """Admits a call with arguments to show, and denies one asked with none."""

    message = "Asked with no arguments."

    def has_permission(
        self, principal: Any, spec: Any, *, arguments: Mapping[str, Any] | None = None
    ) -> bool:
        return arguments is not None


class _Row(serializers.Serializer):
    title = serializers.CharField()


def test_a_many_call_s_refused_row_stands_on_its_checked_top_level() -> None:
    """The kernel asked the checks of the top level before it refused the row, so the row's 400 is told.

    Fails where a refused row is judged again on no arguments, as a failed
    shape is: the check denies that call, and the caller is told 403.
    """
    spec = ServiceSpec(
        service=lambda *, data: data,
        permissions=(_ArgumentsOnly(),),
        validator=SerializerValidator(_Row),
        many=True,
        atomic=False,
    )
    attrs = {"spec": spec, "permission_classes": [], "authentication_classes": []}
    view = type("_View", (ServiceCreateView,), attrs).as_view()
    response = view(factory.post("/", [{"title": "a"}, 5], format="json"))
    assert response.status_code == 400
    assert list(response.data["items"]) == [1]


class _NoScopeOfNothing(PermissionCheck):
    """Lets every caller reach the spec, and refuses the scope question asked of nothing."""

    message = "No scope of nothing."

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True

    def has_scope_permission(self, principal: Any, spec: Any, scope: Any) -> bool:
        return scope is not None


def test_a_create_is_judged_on_the_scope_of_nothing_too() -> None:
    """``dispatch`` asks a create the scope question of nothing, so the judgment asks it as well.

    Fails without that question: the check admits the class-level one, and
    the caller is told what its body lacks rather than refused.
    """
    view = _view(_NoScopeOfNothing(), [SessionAuthentication])
    response = _post(view, {}, username="ada")
    assert (response.status_code, response.data["detail"]) == (403, "No scope of nothing.")


def test_a_write_to_a_row_is_not_judged_on_the_scope_of_nothing() -> None:
    """Its scope question is of the row its arguments name, so it stays unasked on none.

    Fails where every service spec is asked the scope of nothing: the update
    is refused 403 for a body it has not finished.
    """
    spec = ServiceSpec(
        service=lambda *, instance, name: None,
        permissions=(_NoScopeOfNothing(),),
        validator=SerializerValidator(_Name),
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
        ),
    )
    attrs = {"spec": spec, "permission_classes": [], "authentication_classes": []}
    view = type("_View", (ServiceUpdateView,), attrs).as_view()
    author = Author.objects.create(name="Ada")
    response = view(factory.put("/", {}, format="json"), pk=author.pk)
    assert response.status_code == 400
    assert set(response.data) == {"name"}


def test_a_read_is_not_judged_on_the_scope_of_nothing() -> None:
    """A selector spec's scope question is of the rows it reads, so it stays unasked on none.

    Fails where the judgment asks every spec the scope of nothing.
    """
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda *, year: [],
        permissions=(_NoScopeOfNothing(),),
        reads=Parameters.of(Parameter("year", "integer", required=True)),
    )
    attrs = {"spec": spec, "permission_classes": [], "authentication_classes": []}
    view = type("_View", (SelectorListView,), attrs).as_view()
    response = view(factory.get("/", {"year": "x"}))
    assert response.status_code == 400
    assert set(response.data) == {"year"}


@pytest.mark.parametrize("caller", REFUSED)
def test_a_refused_caller_sending_a_body_that_is_no_object_is_refused(caller: str) -> None:
    """The edge refuses such a body before ``check_call`` runs, and judges it on no arguments first."""
    authentication, username, expected = REFUSED[caller]
    view = _view(_check("drf-class"), authentication)
    assert _answer(_post(view, [1, 2], username=username)) == expected


def test_an_admitted_caller_sending_a_body_that_is_no_object_is_told_so() -> None:
    view = _view(_check("drf-class"), [BasicAuthentication])
    response = _post(view, [1, 2], username="editor")
    assert response.status_code == 400
    assert response.data == {"detail": "The body must be an object; got list."}


def test_a_deactivated_caller_is_refused_as_unavailable_whatever_the_body() -> None:
    request = factory.post("/", {}, format="json")
    force_authenticate(request, User.objects.create(username="editor", is_active=False))
    response = _view(_check("kernel-check"), [BasicAuthentication])(request)
    response.render()
    assert response.data == {"detail": "The acting principal is unavailable."}


def test_a_deactivated_caller_s_body_that_is_no_object_is_refused_as_unavailable() -> None:
    """The body that is no object is judged on no arguments, where the
    kernel's ``PrincipalUnavailable`` is a refusal of the caller, as on a
    well-formed body."""
    request = factory.post("/", [1], format="json")
    force_authenticate(request, User.objects.create(username="editor", is_active=False))
    response = _view(_check("kernel-check"), [BasicAuthentication])(request)
    response.render()
    assert (response.status_code, response.data) == (
        403,
        {"detail": "The acting principal is unavailable."},
    )


def test_options_describes_no_method_to_a_deactivated_caller() -> None:
    request = factory.options("/")
    force_authenticate(request, User.objects.create(username="editor", is_active=False))
    answer = _view(_check("kernel-check"), [BasicAuthentication])(request)
    assert "POST" not in answer.data.get("actions", {})


class _RaisesDRFDenial(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        raise DRFPermissionDenied(EDITORS_ONLY)


class _RaisesDenial(PermissionCheck):
    """A kernel check refusing by raising rather than answering ``False``."""

    def __init__(self, raised: Exception) -> None:
        self.raised = raised

    def has_permission(self, principal: Any, spec: Any) -> bool:
        raise self.raised


RAISING_CHECKS = {
    "a DRF class raising DRF's PermissionDenied": lambda: DRFPermissionCheck([_RaisesDRFDenial]),
    "a kernel check raising Django's PermissionDenied": lambda: _RaisesDenial(
        DjangoPermissionDenied(EDITORS_ONLY)
    ),
    "a kernel check raising DRF's PermissionDenied": lambda: _RaisesDenial(
        DRFPermissionDenied(EDITORS_ONLY)
    ),
}


@pytest.mark.parametrize("case", RAISING_CHECKS)
def test_a_check_raising_a_refusal_refuses_whatever_the_body(case: str) -> None:
    """A refusal raised is a refusal, never a check that cannot answer without
    its arguments: OPTIONS hides the method and an incomplete POST is answered
    403, as a well-formed one is."""
    view = _view(RAISING_CHECKS[case](), [SessionAuthentication])
    user = User.objects.create(username="ada")
    options, posted = factory.options("/"), factory.post("/", {}, format="json")
    force_authenticate(options, user)
    force_authenticate(posted, user)
    assert "POST" not in view(options).data.get("actions", {})
    assert view(posted).status_code == 403


OPTIONS_CASES = {
    # (the spec's check, who signs in, whether the method is described)
    "a DRF class refusing an anonymous caller": (lambda: _check("drf-class"), None, False),
    "a DRF class refusing a signed-in caller": (lambda: _check("drf-class"), "ada", False),
    "a DRF class admitting an editor": (lambda: _check("drf-class"), "editor", True),
    "a kernel check refusing a signed-in caller": (lambda: _check("kernel-check"), "ada", False),
    "a kernel check admitting an editor": (lambda: _check("kernel-check"), "editor", True),
    "a scope check refusing a create's nothing": (_NoScopeOfNothing, "ada", False),
    "a check that reads the arguments": (_OwnerOnly, "ada", True),
}


@pytest.mark.parametrize("case", OPTIONS_CASES)
def test_options_hides_a_method_exactly_when_its_write_is_refused_first(case: str) -> None:
    """OPTIONS describes the POST to exactly the callers whose incomplete POST is told its 400.

    The disagreement this closes: OPTIONS hid the schema from a caller the
    checks refuse, and the POST's 400 then listed its fields. Fails for the
    scope check where OPTIONS asks ``authorize`` alone, and for the check
    reading the arguments, which raises asked with none, where it does not
    judge as the edge judges.
    """
    build, username, described = OPTIONS_CASES[case]
    view = _view(build(), [SessionAuthentication])
    user = None if username is None else User.objects.create(username=username)
    options, posted = factory.options("/"), factory.post("/", {}, format="json")
    if user is not None:
        force_authenticate(options, user)
        force_authenticate(posted, user)
    answer = view(options)
    assert answer.status_code == 200
    assert ("POST" in answer.data.get("actions", {})) is described
    assert (view(posted).status_code == 400) is described


@pytest.mark.parametrize("method", ["options", "post"])
def test_a_misconfigured_spec_fails_as_a_well_formed_call_fails(method: str) -> None:
    """A spec declaring no permissions is a configuration error, never judged as a check that cannot answer.

    Fails where the judgment on no arguments swallows it with the rest: OPTIONS
    then describes the method and an incomplete POST is told its 400, while
    every well-formed POST raises.
    """
    spec = ServiceSpec(
        service=lambda *, submission_id, outcome: None, validator=SerializerValidator(_Review)
    )
    attrs = {"spec": spec, "permission_classes": [], "authentication_classes": []}
    view = type("_View", (ServiceCreateView,), attrs).as_view()
    request = getattr(factory, method)("/", {}, format="json")
    with pytest.raises(ImproperlyConfigured, match="declares no permissions"):
        view(request)
