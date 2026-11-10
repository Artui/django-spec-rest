from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rest_framework.request import Request


@dataclass(frozen=True)
class OfflineServiceView:
    """A concrete [`ServiceView`][django_spec_rest.types.service_view.ServiceView] for dispatching a spec outside an HTTP request."""

    request: Request
    action: str | None = None
    kwargs: dict[str, Any] = field(default_factory=dict)
