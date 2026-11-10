from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.services.action_unavailable import ActionUnavailable
from django_service_specs.services.additional_input_required import AdditionalInputRequired
from django_service_specs.services.service_conflict import ServiceConflict
from django_service_specs.services.service_error import ServiceError
from django_service_specs.services.service_not_found import ServiceNotFound
from django_service_specs.services.service_validation_error import ServiceValidationError
from rest_framework import exceptions as drf_exceptions
from rest_framework import status as drf_status


class _ServiceAPIException(drf_exceptions.APIException):
    """Default DRF mapping for non-validation
    [`ServiceError`][django_service_specs.services.service_error.ServiceError]."""

    status_code = drf_status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "Service error."
    default_code = "service_error"


class _AdditionalInputAPIException(_ServiceAPIException):
    """The ``422`` an
    [`AdditionalInputRequired`][django_service_specs.services.additional_input_required.AdditionalInputRequired]
    carrying a schema answers with: ``{"detail": <message>, "schema": <schema>}``."""

    def __init__(self, message: str, schema: Mapping[str, Any]) -> None:
        self.schema: dict[str, Any] = dict(schema)
        super().__init__({"detail": message, "schema": self.schema})


class _ConflictAPIException(drf_exceptions.APIException):
    """DRF mapping for [`ServiceConflict`][django_service_specs.services.service_conflict.ServiceConflict]."""  # noqa: E501

    status_code = drf_status.HTTP_409_CONFLICT
    default_detail = "Conflict."
    default_code = "conflict"


def map_service_error(exc: ServiceError) -> drf_exceptions.APIException:
    """Translate a framework-agnostic service error into a DRF exception."""
    if isinstance(exc, ServiceValidationError):
        return drf_exceptions.ValidationError(exc.detail)
    if isinstance(exc, ServiceNotFound):
        return drf_exceptions.NotFound(str(exc))
    if isinstance(exc, ActionUnavailable):
        return _ConflictAPIException({"detail": str(exc), "code": exc.code})
    if isinstance(exc, ServiceConflict):
        return _ConflictAPIException(str(exc))
    if isinstance(exc, AdditionalInputRequired) and exc.schema is not None:
        return _AdditionalInputAPIException(str(exc), exc.schema)
    return _ServiceAPIException(str(exc))
