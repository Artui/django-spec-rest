from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Final

from django_service_specs.services.service_error import ServiceError
from django_service_specs.types.dispatch_error import DispatchError
from rest_framework.exceptions import (
    APIException,
    NotAuthenticated,
    PermissionDenied,
    ValidationError,
)

from django_spec_rest.service_specs.drf_not_authenticated import DRFNotAuthenticated
from django_spec_rest.service_specs.drf_not_permitted import DRFNotPermitted
from django_spec_rest.service_specs.drf_service_validation_error import (
    DRFServiceValidationError,
)

TRANSLATED_FROM: Final = "_translated_from"
"""The attribute a translated refusal carries the exception it was translated from under.

The DRF edge reads it to restore what the author raised. A refusal this
package raises itself, such as a permission class answering ``False``, carries none,
so it is never mistaken for one translated here.
"""


@contextmanager
def translate_drf_refusals() -> Generator[None]:
    """Re-raise the DRF refusals raised inside the block as the kernel's classes, still DRF's."""
    try:
        yield
    except APIException as exc:
        twin = _kernel_twin(exc)
        if twin is None:
            raise
        raise twin from exc


def _kernel_twin(exc: APIException) -> APIException | None:
    """The kernel's class ``exc`` leaves as, or ``None`` to leave it as raised."""
    twin = _built(exc)
    if twin is None:
        return None
    twin.detail = exc.detail
    twin.status_code = exc.status_code
    setattr(twin, TRANSLATED_FROM, exc)
    return twin


def _built(exc: APIException) -> APIException | None:
    """The twin of ``exc``'s class, built from its message and code or its detail."""
    if isinstance(exc, DispatchError | ServiceError):
        return None
    if isinstance(exc, NotAuthenticated):
        return DRFNotAuthenticated(_message(exc))
    if isinstance(exc, PermissionDenied):
        return DRFNotPermitted(_message(exc))
    if isinstance(exc, ValidationError):
        return DRFServiceValidationError(exc.detail)
    return None


def _message(exc: APIException) -> str | None:
    """A denial's message, or ``None`` for the kernel's default where its detail is no message."""
    return exc.detail if isinstance(exc.detail, str) else None


__all__ = ["TRANSLATED_FROM", "translate_drf_refusals"]
