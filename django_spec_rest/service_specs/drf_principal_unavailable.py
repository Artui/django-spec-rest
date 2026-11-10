from __future__ import annotations

from django_service_specs.authorization.principal_unavailable import (
    PrincipalUnavailable as KernelPrincipalUnavailable,
)
from rest_framework.exceptions import PermissionDenied


class DRFPrincipalUnavailable(KernelPrincipalUnavailable, PermissionDenied):
    """The kernel's ``PrincipalUnavailable`` and DRF's ``PermissionDenied``, for a principal."""

    def __init__(self, message: str | None = None, code: str | None = None) -> None:
        KernelPrincipalUnavailable.__init__(self, message)
        PermissionDenied.__init__(self, self.message, code)

    @classmethod
    def from_kernel(cls, exc: KernelPrincipalUnavailable) -> DRFPrincipalUnavailable:
        """The kernel's refusal ``exc`` as this class, with its message."""
        return cls(exc.message)
