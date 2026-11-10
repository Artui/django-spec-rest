from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rest_framework.request import Request

from django_spec_rest.types.offline_service_view import OfflineServiceView


@dataclass(frozen=True)
class OfflineContext:
    """The HTTP-surrogate a spec needs when dispatched off the HTTP path."""

    user: Any
    request: Request
    view: OfflineServiceView
