from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from django_spec_rest.views.utils import resolve_callable_kwargs


def resolve_success_status(
    success_status: int | Callable[..., int] | None,
    *,
    default: int,
    pool: Mapping[str, Any],
) -> int:
    """Resolve a ``ServiceSpec.success_status`` to an HTTP status code."""
    if success_status is None:
        return default
    if isinstance(success_status, int):
        return success_status
    return success_status(**resolve_callable_kwargs(success_status, dict(pool)))
