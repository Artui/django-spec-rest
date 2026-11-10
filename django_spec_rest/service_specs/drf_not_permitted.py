from __future__ import annotations

from django_service_specs.authorization.not_permitted import NotPermitted as KernelNotPermitted
from rest_framework.exceptions import PermissionDenied


class DRFNotPermitted(KernelNotPermitted, PermissionDenied):
    """Refused by a check: the kernel's ``NotPermitted`` and DRF's ``PermissionDenied``."""

    def __init__(self, message: str | None = None, code: str | None = None) -> None:
        KernelNotPermitted.__init__(self, message)
        PermissionDenied.__init__(self, self.message, code)

    @classmethod
    def from_kernel(cls, exc: KernelNotPermitted) -> DRFNotPermitted:
        """The kernel's denial ``exc`` as this class, with its message."""
        return cls(exc.message)
