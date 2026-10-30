"""An anonymous client over a live view: the kernel's principal is DRF's unauthenticated user.

The view hands the kernel ``request.user``, which DRF sets to the project's
``UNAUTHENTICATED_USER`` for a client no authenticator recognised, read when
the request is served. For a project setting ``UNAUTHENTICATED_USER = None``
the kernel route hands the kernel that ``None``, which it takes, rather than
acting as Django's ``AnonymousUser``.
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


def test_a_project_with_no_unauthenticated_user_hands_the_kernel_none() -> None:
    """The decided answer: the edge passes ``request.user`` on as DRF set it.

    A project that sets ``UNAUTHENTICATED_USER = None`` has chosen that an
    unrecognised client has no user, and the kernel takes ``None`` as a principal,
    so the edge does not stand ``AnonymousUser`` in for it.
    """
    response, seen = _served(UNAUTHENTICATED_USER=None)

    assert response.status_code == 204, response.data
    assert seen == [None]
