from __future__ import annotations

from typing import Any

from django_spec_rest.service_specs.drf_not_authenticated import DRFNotAuthenticated
from django_spec_rest.service_specs.drf_not_permitted import DRFNotPermitted


def permission_denied(
    request: Any, message: str | None = None, code: str | None = None
) -> DRFNotAuthenticated | DRFNotPermitted:
    """The refusal of a caller ``request`` carries, decided as DRF's view decides it."""
    if getattr(request, "authenticators", ()) and not request.successful_authenticator:
        return DRFNotAuthenticated()
    return DRFNotPermitted(message, code)
