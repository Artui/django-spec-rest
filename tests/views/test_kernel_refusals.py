"""The kernel route's refusal map: total, ordered, and each row answering with its own DRF answer.

Every row has a test asserting its own answer and asserting that it is not the
answer of the row the refusal falls to with that row deleted, so mutating a
row out fails a named test even where the map stays total:

- ``APIException`` (falls to the ``DRFInvalidArguments`` row, which would rebuild
  the dual-base refusal as a new one):
  ``test_a_refusal_that_is_drf_s_already_leaves_as_raised``, and the author's
  own exception where the refusal was translated from one
  (``tests/views/test_drf_refusals_restored_on_the_edge.py``);
- ``DRFInvalidArguments`` (falls to ``DispatchError``, a ``detail`` sentence):
  ``test_a_missing_argument_is_drf_s_400_by_field``;
- ``NotPermitted`` / ``PrincipalUnavailable`` (fall to ``DispatchError``, a
  ``400``): ``test_a_denied_principal_is_403``,
  ``test_a_deactivated_principal_is_403``;
- ``DispatchError`` (unanswered without it, with the totality test):
  ``test_a_bare_dispatch_error_is_400_with_its_sentence``;
- ``ServiceError`` (unanswered without it, with the totality test):
  ``test_a_service_s_refusal_is_answered_by_map_service_error``, one case per
  subclass. The subclasses are one row on purpose: ``map_service_error`` is
  the answer for all of them and a row each pointing at it could not be told
  from the base row it falls to, so each subclass's answer is held by its
  case here and by its branch in ``test_map_service_error.py``.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User
from django_service_specs import (
    ActionUnavailable,
    AdditionalInputRequired,
    DispatchError,
    Output,
    PermissionCheck,
    Presenter,
    ServiceConflict,
    ServiceError,
    ServiceNotFound,
    ServiceSpec,
    ServiceValidationError,
    Unrestricted,
    unanswered_refusals,
)
from django_service_specs import InvalidArguments as KernelInvalidArguments
from django_service_specs.authorization.not_permitted import NotPermitted as KernelNotPermitted
from django_service_specs.authorization.principal_unavailable import (
    PrincipalUnavailable as KernelPrincipalUnavailable,
)
from rest_framework import serializers
from rest_framework.authentication import BasicAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest.dispatch.kernel_refusals import (
    KERNEL_REFUSALS,
    answer_refusal,
    answering_refusals,
)
from django_spec_rest.service_specs.drf_invalid_arguments import DRFInvalidArguments
from django_spec_rest.service_specs.drf_not_authenticated import DRFNotAuthenticated
from django_spec_rest.service_specs.drf_not_permitted import DRFNotPermitted
from django_spec_rest.service_specs.drf_principal_unavailable import DRFPrincipalUnavailable
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.views.test_kernel_views import _CreateView

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()


class _Deny(PermissionCheck):
    message = "Not for you."

    def has_permission(self, *args: Any, **kwargs: Any) -> bool:
        return False


class _Input(serializers.Serializer):
    title = serializers.CharField()


def _raising(exc: BaseException) -> Any:
    def service() -> None:
        raise exc

    return service


def _call(spec: ServiceSpec, body: Any = None, *, user: Any = None) -> Response:
    view = type("_View", (_CreateView,), {"spec": spec}).as_view()
    request = factory.post("/", body or {}, format="json")
    if user is not None:
        force_authenticate(request, user=user)
    return view(request)


def test_the_map_answers_every_refusal_the_kernel_raises() -> None:
    assert unanswered_refusals(KERNEL_REFUSALS) == ()


def test_a_refusal_that_is_drf_s_already_leaves_as_raised() -> None:
    raised = DRFInvalidArguments({"title": ["Too long."]})
    assert answer_refusal(raised) is raised


def test_a_missing_argument_is_drf_s_400_by_field() -> None:
    spec = ServiceSpec(
        service=lambda: None, permissions=(Unrestricted(),), validator=SerializerValidator(_Input)
    )
    response = _call(spec, {})
    assert response.status_code == 400
    assert list(response.data) == ["title"]
    assert response.data["title"][0].code == "required"
    assert "detail" not in response.data


def test_a_subclass_of_the_kernel_s_invalid_arguments_keeps_its_message() -> None:
    class _Worded(KernelInvalidArguments):
        default_message = "Worded otherwise."

    answer = answer_refusal(_Worded({"title": ["x"]}))
    assert isinstance(answer, DRFInvalidArguments)
    assert answer.message == "Worded otherwise."


def test_a_denied_principal_is_403() -> None:
    response = _call(ServiceSpec(service=lambda: None, permissions=(_Deny(),)))
    assert response.status_code == 403
    assert response.data == {"detail": "Not for you."}


def test_a_deactivated_principal_is_403() -> None:
    gone = User.objects.create(username="gone", is_active=False)
    spec = ServiceSpec(service=lambda: None, permissions=(Unrestricted(),))
    response = _call(spec, user=gone)
    assert response.status_code == 403
    assert response.data["detail"].code == "permission_denied"


def _served_on(user: Any = None) -> Request:
    """A request served with ``BasicAuthentication``, by ``user`` or by nobody it recognised."""
    request = factory.post("/", {}, format="json")
    if user is not None:
        force_authenticate(request, user=user)
    return Request(request, authenticators=[BasicAuthentication()])


class TestADenialWithTheRequestItRefused:
    """The kernel's denial, given the request, is answered as DRF's view answers a refusal.

    Over HTTP: ``tests/views/test_an_anonymous_caller_refused.py``.
    """

    def test_a_caller_nobody_recognised_is_asked_to_authenticate(self) -> None:
        answer = answer_refusal(KernelNotPermitted("Not for you."), _served_on())
        assert isinstance(answer, DRFNotAuthenticated)
        assert answer.detail == "Authentication credentials were not provided."

    def test_a_recognised_caller_is_refused_with_the_check_s_message(self) -> None:
        user = User.objects.create(username="ada")
        answer = answer_refusal(KernelNotPermitted("Not for you."), _served_on(user))
        assert type(answer) is DRFNotPermitted
        assert answer.detail == "Not for you."

    def test_with_no_request_a_kernel_denial_is_the_map_s_403(self) -> None:
        answer = answer_refusal(KernelNotPermitted("Not for you."))
        assert type(answer) is DRFNotPermitted
        assert answer.detail == "Not for you."

    def test_a_refusal_that_is_no_denial_is_the_map_s_with_a_request(self) -> None:
        """A principal who cannot act is no permission refusing it: still 403."""
        answer = answer_refusal(KernelPrincipalUnavailable(), _served_on())
        assert isinstance(answer, DRFPrincipalUnavailable)

    def test_a_denial_that_is_drf_s_already_leaves_as_raised(self) -> None:
        """``DRFPermissionCheck`` decided its own refusal with the request it asked."""
        raised = DRFNotPermitted("Not for you.")
        assert answer_refusal(raised, _served_on()) is raised

    def test_the_block_hands_its_request_to_the_map(self) -> None:
        with pytest.raises(DRFNotAuthenticated), answering_refusals(_served_on()):
            raise KernelNotPermitted("Not for you.")


def test_a_bare_dispatch_error_is_400_with_its_sentence() -> None:
    spec = ServiceSpec(
        service=_raising(DispatchError("Not this way.")), permissions=(Unrestricted(),)
    )
    response = _call(spec)
    assert response.status_code == 400
    assert response.data == {"detail": "Not this way."}
    assert response.data["detail"].code == "invalid"


@pytest.mark.parametrize(
    ("raised", "status", "body"),
    [
        (ServiceValidationError({"title": ["Taken."]}), 400, {"title": ["Taken."]}),
        (ServiceNotFound("No such row."), 404, {"detail": "No such row."}),
        (
            ActionUnavailable(code="closed", message="It is closed."),
            409,
            {"detail": "It is closed.", "code": "closed"},
        ),
        (ServiceConflict("Busy."), 409, {"detail": "Busy."}),
        (
            AdditionalInputRequired(
                "One more.", schema={"type": "object", "properties": {"ok": {"default": False}}}
            ),
            422,
            {
                "detail": "One more.",
                "schema": {"type": "object", "properties": {"ok": {"default": False}}},
            },
        ),
        (ServiceError("Could not."), 422, {"detail": "Could not."}),
    ],
    ids=["validation", "not-found", "unavailable", "conflict", "input-required", "service"],
)
def test_a_service_s_refusal_is_answered_by_map_service_error(
    raised: BaseException, status: int, body: dict[str, Any]
) -> None:
    """``map_service_error``'s answers, the schema served as raised, ``False``
    and all."""
    response = _call(ServiceSpec(service=_raising(raised), permissions=(Unrestricted(),)))
    assert response.status_code == status
    assert response.data == body


def test_a_presenter_s_refusal_is_answered_by_the_map_too() -> None:
    """``present`` runs after the kernel's ``dispatch`` and inside the map, so
    a kernel presenter refusing what it was asked to present is DRF's ``400``,
    not a fault."""

    class _Refusing(Presenter):
        def output(self) -> Output:
            return Output()

        def present(self, value: Any) -> Any:
            raise KernelInvalidArguments({"fields": ["No such field."]})

    spec = ServiceSpec(service=lambda: 1, permissions=(Unrestricted(),), presenter=_Refusing())
    response = _call(spec)
    assert response.status_code == 400
    assert response.data == {"fields": ["No such field."]}
