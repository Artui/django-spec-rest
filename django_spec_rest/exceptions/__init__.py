"""Framework-agnostic exceptions raised by service code.

These classes have **no DRF imports**. The view layer is responsible for
translating them into HTTP responses.
"""

from django_spec_rest.exceptions.action_unavailable import ActionUnavailable
from django_spec_rest.exceptions.additional_input_required import (
    AdditionalInputRequired,
)
from django_spec_rest.exceptions.service_conflict import ServiceConflict
from django_spec_rest.exceptions.service_error import ServiceError
from django_spec_rest.exceptions.service_not_found import ServiceNotFound
from django_spec_rest.exceptions.service_validation_error import (
    ServiceValidationError,
)

__all__ = [
    "ActionUnavailable",
    "AdditionalInputRequired",
    "ServiceConflict",
    "ServiceError",
    "ServiceNotFound",
    "ServiceValidationError",
]
