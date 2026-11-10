from __future__ import annotations

from typing import Any, Protocol

from rest_framework.request import Request


class ServiceView(Protocol):
    """Minimal structural shape of a view as exposed to a kwargs provider."""

    request: Request
    kwargs: dict[str, Any]
    action: str | None
