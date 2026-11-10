from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.views.utils import resolve_callable_kwargs


def apply_response_finalizer(
    finalizer: Callable[..., Response | None] | None,
    response: Response,
    *,
    request: Request,
    view: Any,
    result: Any,
    instance: Any = None,
    data: Any = None,
    variant: str | None = None,
) -> Response:
    """Apply ``ServiceSpec.response_finalizer`` to a freshly built 2xx response."""
    if finalizer is None:
        return response
    pool: dict[str, Any] = {
        "response": response,
        "request": request,
        "view": view,
        "result": result,
    }
    if instance is not None:
        pool["instance"] = instance
    if data is not None:
        pool["data"] = data
    if variant is not None:
        pool["variant"] = variant
    finalized = finalizer(**resolve_callable_kwargs(finalizer, pool))
    return finalized if finalized is not None else response
