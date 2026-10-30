"""An anonymous client over a live view: the kernel's principal is DRF's unauthenticated user.

The view hands the kernel ``request.user``, which DRF sets to the project's
``UNAUTHENTICATED_USER`` for a client no authenticator recognised, read when
the request is served. drfs' edge acted as Django's ``AnonymousUser`` for a
project setting ``UNAUTHENTICATED_USER = None``; the kernel route hands the
kernel that ``None``, which it takes, so that case is a strict xfail naming
the edge's line until the edge decides.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import override_settings
from django_service_specs import ServiceSpec, Unrestricted
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()


class Guest(AnonymousUser):
    """A project's own unauthenticated user."""


class _CreateView(ServiceCreateView):
    """A create view over a kernel spec, its own permission classes answering for it."""

    permission_classes: Any = []

    def get_permissions(self) -> list[Any]:
        return [permission() for permission in self.permission_classes]


def _served(**settings: Any) -> tuple[Response, list[Any]]:
    seen: list[Any] = []
    spec = ServiceSpec(service=lambda *, user: seen.append(user), permissions=(Unrestricted(),))
    view = type("_View", (_CreateView,), {"spec": spec}).as_view()
    with override_settings(REST_FRAMEWORK=settings):
        response = view(factory.post("/", {}, format="json"))
    return response, seen


def test_an_anonymous_client_acts_as_the_unauthenticated_user() -> None:
    response, seen = _served()

    assert response.status_code == 204
    (user,) = seen
    assert isinstance(user, AnonymousUser)


def test_the_unauthenticated_user_is_the_project_s() -> None:
    response, seen = _served(UNAUTHENTICATED_USER=f"{__name__}.Guest")

    assert response.status_code == 204
    (user,) = seen
    assert type(user) is Guest


@pytest.mark.xfail(
    strict=True,
    reason=(
        "dispatch_kernel_spec hands the kernel request.user as it is, None under "
        "UNAUTHENTICATED_USER = None, where drfs' edge acted as AnonymousUser"
    ),
)
def test_a_project_with_no_unauthenticated_user_still_acts_as_anonymous() -> None:
    response, seen = _served(UNAUTHENTICATED_USER=None)

    assert response.status_code == 204, response.data
    (user,) = seen
    assert isinstance(user, AnonymousUser)
