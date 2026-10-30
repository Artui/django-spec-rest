"""``OfflineServiceView`` — a concrete ``ServiceView`` for off-HTTP dispatch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rest_framework.request import Request


@dataclass(frozen=True)
class OfflineServiceView:
    """A concrete
    [`ServiceView`][django_spec_rest.types.service_view.ServiceView] for
    dispatching a spec outside an HTTP request.

    Spec ``kwargs`` / ``extend_queryset`` / context providers are typed against
    [`ServiceView`][django_spec_rest.types.service_view.ServiceView] — the
    structural ``request`` / ``kwargs`` / ``action`` surface. When a spec is
    dispatched off the HTTP path (a Pydantic-AI toolset, the MCP server, a
    management command) there is no DRF view, so this frozen value stands in:

    - ``request`` — the synthetic DRF ``Request`` built by
      [`build_offline_context`][django_spec_rest.service_specs.build_offline_context.build_offline_context].
    - ``action`` — an optional label identifying the operation; ``None`` when the caller
      has no meaningful action name.
    - ``kwargs`` — the URL-kwargs equivalent (e.g. parent ids), empty by default.
    """

    request: Request
    action: str | None = None
    kwargs: dict[str, Any] = field(default_factory=dict)
