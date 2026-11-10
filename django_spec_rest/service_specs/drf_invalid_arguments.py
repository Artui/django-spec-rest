from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.parameters.invalid_arguments import (
    InvalidArguments as KernelInvalidArguments,
)
from rest_framework.exceptions import ValidationError


class DRFInvalidArguments(KernelInvalidArguments, ValidationError):
    """The arguments were refused, as both the kernel's ``InvalidArguments`` and DRF's ``ValidationError``."""

    def __init__(self, detail: Mapping[Any, Any], code: str | None = None) -> None:
        # The kernel's first, for ``message`` and whatever else it sets; its ``super()`` chain reaches DRF's with the default message, and the kernel then overwrites ``detail`` with plain strings, which DRF's run here replaces with the same tree as ``ErrorDetail``s.
        KernelInvalidArguments.__init__(self, detail)
        ValidationError.__init__(self, self.detail, code)

    @classmethod
    def from_kernel(cls, exc: KernelInvalidArguments) -> DRFInvalidArguments:
        """The kernel's ``exc`` as this class: the same tree, every message's code and ``message``."""
        twin = cls(exc.detail)
        twin.message = exc.message
        return twin
