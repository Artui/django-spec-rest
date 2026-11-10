from __future__ import annotations

from typing import Any

from django_service_specs.services.service_validation_error import (
    ServiceValidationError as KernelServiceValidationError,
)
from rest_framework.exceptions import ValidationError


class DRFServiceValidationError(KernelServiceValidationError, ValidationError):
    """Refused input: the kernel's ``ServiceValidationError`` and DRF's ``ValidationError``."""

    detail: Any

    def __init__(self, detail: Any, code: str | None = None) -> None:
        KernelServiceValidationError.__init__(self, detail)
        ValidationError.__init__(self, detail, code)
