from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.auth.models import User
from django_service_specs import ServiceSpec, Unrestricted
from django_service_specs.dispatch.check_seeds import check_seeds
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest.dispatch.kernel_edge import dispatch_kernel_spec
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.views.utils import view_call_context
from tests.views.test_kernel_views import _CreateView

factory = APIRequestFactory()
OPEN = (Unrestricted(),)
FORMATS = pytest.mark.parametrize("fmt", ["json", "multipart"])


def open_spec(service: Callable[..., Any], serializer: Any, **fields: Any) -> ServiceSpec:
    """A non-atomic spec over ``serializer``, open to every caller."""
    return ServiceSpec(
        service=service,
        permissions=OPEN,
        validator=SerializerValidator(serializer),
        atomic=False,
        **fields,
    )


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


def dispatch_live(
    spec: ServiceSpec, body: Any, *, fmt: str = "json", user: User | None = None
) -> Any:
    """``dispatch_kernel_spec`` of ``spec`` over a live view's request for ``body``."""
    check_seeds(spec)
    return dispatch_kernel_spec(spec, **_live(body, fmt, user))
