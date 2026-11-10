from __future__ import annotations

from django_service_specs.authorization.not_permitted import NotPermitted as KernelNotPermitted
from rest_framework.exceptions import NotAuthenticated


class DRFNotAuthenticated(KernelNotPermitted, NotAuthenticated):
    """No principal authenticated: the kernel's ``NotPermitted`` and DRF's ``NotAuthenticated``."""

    def __init__(self, message: str | None = None, code: str | None = None) -> None:
        KernelNotPermitted.__init__(
            self, message if message is not None else str(NotAuthenticated.default_detail)
        )
        NotAuthenticated.__init__(self, self.message, code)
