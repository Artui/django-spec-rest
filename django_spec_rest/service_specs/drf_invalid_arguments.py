from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.parameters.invalid_arguments import (
    InvalidArguments as KernelInvalidArguments,
)
from rest_framework.exceptions import ValidationError


class DRFInvalidArguments(KernelInvalidArguments, ValidationError):
    """Refused as both the kernel's ``InvalidArguments`` and DRF's ``ValidationError``."""

    detail: Any

    def __init__(self, detail: Mapping[Any, Any], code: str | None = None) -> None:
        # Kernel first; DRF's init, via ``super()``, turns ``detail`` into ``ErrorDetail``s.
        KernelInvalidArguments.__init__(self, detail)
        ValidationError.__init__(self, self.detail, code)

    @classmethod
    def from_kernel(cls, exc: KernelInvalidArguments) -> DRFInvalidArguments:
        """The kernel's ``exc`` as this class: same tree, each message's code and ``message``."""
        twin = cls(exc.detail)
        twin.message = exc.message
        return twin
