from __future__ import annotations

from typing import Any

from django_service_specs.mutations.register_row_error import register_row_error
from rest_framework.exceptions import ValidationError


def register_drf_row_errors() -> None:
    """Register DRF's ``ValidationError`` as a refusal the kernel re-roots under the row that raised it."""
    register_row_error(ValidationError, _validation_error_detail)


def _validation_error_detail(exc: ValidationError) -> Any:
    """DRF's detail as it stands: a field map or a list of the row's own messages, codes and all."""
    return exc.detail
