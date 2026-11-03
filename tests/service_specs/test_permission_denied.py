"""``permission_denied``: the refusal DRF's view decides, for the request a caller is on.

The two halves of its one condition are each held: a caller an authenticator
recognised is denied (test_a_recognised_caller_is_denied_with_the_message_and_code,
which fails without the second), and so is a request with no authenticator
(test_off_http_a_refusal_is_the_denial, which fails without the first, since the
offline request reports no successful authenticator either).
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser, User
from rest_framework.authentication import BasicAuthentication
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest.service_specs.build_offline_context import build_offline_context
from django_spec_rest.service_specs.drf_not_authenticated import DRFNotAuthenticated
from django_spec_rest.service_specs.drf_not_permitted import DRFNotPermitted
from django_spec_rest.service_specs.permission_denied import permission_denied

factory = APIRequestFactory()


def _served_on(user: Any = None) -> Request:
    request = factory.get("/")
    if user is not None:
        force_authenticate(request, user=user)
    return Request(request, authenticators=[BasicAuthentication()])


def test_a_caller_nobody_recognised_is_asked_to_authenticate() -> None:
    """DRF's wording and code, never the permission's: DRF raises it bare."""
    refusal = permission_denied(_served_on(), "Members only.", "members")
    assert isinstance(refusal, DRFNotAuthenticated)
    assert refusal.detail == "Authentication credentials were not provided."
    assert refusal.detail.code == "not_authenticated"


@pytest.mark.django_db
def test_a_recognised_caller_is_denied_with_the_message_and_code() -> None:
    refusal = permission_denied(_served_on(User.objects.create(username="ada")), "No.", "nope")
    assert type(refusal) is DRFNotPermitted
    assert (refusal.detail, refusal.detail.code) == ("No.", "nope")


def test_a_request_with_no_authenticator_is_denied() -> None:
    refusal = permission_denied(Request(factory.get("/")), "No.")
    assert type(refusal) is DRFNotPermitted
    assert refusal.detail == "No."


def test_off_http_a_refusal_is_the_denial() -> None:
    """The offline request has no authenticator, so an anonymous principal is denied."""
    request = build_offline_context(AnonymousUser()).request
    assert type(permission_denied(request)) is DRFNotPermitted


def test_a_stand_in_that_is_not_drf_s_is_read_as_having_no_authenticator() -> None:
    assert type(permission_denied(object())) is DRFNotPermitted


def test_with_no_message_the_denial_is_the_kernel_s() -> None:
    refusal = permission_denied(Request(factory.get("/")))
    assert refusal.detail == "You do not have permission to perform this action."
