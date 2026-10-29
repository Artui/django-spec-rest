"""How the server-value modules call a kernel spec: over HTTP, and through the edge's two cores.

Shared by the ``test_*server_value*``, ``test_a_typed_provider*`` and
``test_*seed_named*`` modules of this directory, which each ask one question of
the kernel route: which value a service is handed when the server and the
client both name a key. Every spec they declare is the kernel's own, with
``SerializerValidator`` as its seat, and every call goes through the view or
the edge, never a helper the kernel route added.

- ``post`` drives ``_CreateView`` (``test_kernel_views``) through
  ``as_view()``, as a client does.
- ``CORES`` drives ``dispatch_kernel_spec`` and ``adispatch_kernel_spec`` over
  a live view's request, in either body format, so the async core is held to
  the same answers; ``tests/views/test_kernel_edge.py`` holds the two cores'
  parity in general.

Both ask the kernel's ``check_seeds`` of the spec first, the check a mount
makes of a kernel spec, so every spec these modules dispatch is one a view
would take: an optional read has a default on its keyword, and no keyword is
left for nothing to fill. The edge's cores never pass through ``as_view()``,
so without it a spec no view could mount would still answer here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth.models import User
from django_service_specs import ServiceSpec, Unrestricted
from django_service_specs.dispatch.check_seeds import check_seeds
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest.dispatch.kernel_edge import adispatch_kernel_spec, dispatch_kernel_spec
from django_spec_rest.views.utils import view_call_context
from tests.views.test_kernel_views import _CreateView

factory = APIRequestFactory()
OPEN = (Unrestricted(),)
FORMATS = pytest.mark.parametrize("fmt", ["json", "multipart"])


def post(
    spec: ServiceSpec,
    body: Any,
    *,
    fmt: str = "json",
    user: User | None = None,
    view: type[_CreateView] = _CreateView,
) -> Response:
    """POST ``body`` to a create view serving ``spec``, as ``user`` where one is given."""
    check_seeds(spec)
    request = factory.post("/", body, format=fmt)
    if user is not None:
        force_authenticate(request, user=user)
    return type("_View", (view,), {"spec": spec}).as_view()(request)


def _live(body: Any, fmt: str, user: User | None) -> dict[str, Any]:
    """A live view's request for ``body``, as the view hands the edge its parts."""
    view = _CreateView()
    django_request = factory.post("/", body, format=fmt)
    if user is not None:
        force_authenticate(django_request, user=user)
    view.args, view.kwargs, view.format_kwarg = (), {}, None
    request = view.initialize_request(django_request)
    view.request = request
    return {"view": view, "request": request, "call_context": view_call_context(view, request)}


def _sync(spec: ServiceSpec, body: Any, *, fmt: str = "json", user: User | None = None) -> Any:
    check_seeds(spec)
    return dispatch_kernel_spec(spec, **_live(body, fmt, user))


def _async(spec: ServiceSpec, body: Any, *, fmt: str = "json", user: User | None = None) -> Any:
    check_seeds(spec)
    return async_to_sync(adispatch_kernel_spec)(spec, **_live(body, fmt, user))


Core = Callable[..., Any]
CORES = pytest.mark.parametrize("core", [_sync, _async], ids=["sync", "async"])
