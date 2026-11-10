from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from django_service_specs.authorization.not_permitted import NotPermitted as KernelNotPermitted
from django_service_specs.authorization.principal_unavailable import (
    PrincipalUnavailable as KernelPrincipalUnavailable,
)
from django_service_specs.parameters.invalid_arguments import (
    InvalidArguments as KernelInvalidArguments,
)
from django_service_specs.types.dispatch_error import DispatchError
from rest_framework.exceptions import APIException

from django_spec_rest.service_specs.drf_invalid_arguments import DRFInvalidArguments
from django_spec_rest.service_specs.drf_not_permitted import DRFNotPermitted
from django_spec_rest.service_specs.drf_principal_unavailable import DRFPrincipalUnavailable


@contextmanager
def translate_dispatch_errors() -> Generator[None]:
    """Re-raise the kernel's ``DispatchError``s as this package's dual-base classes."""
    try:
        yield
    except DispatchError as exc:
        twin = _drf_twin(exc)
        if twin is None:
            raise
        raise twin from exc


def _drf_twin(exc: DispatchError) -> DispatchError | None:
    """The dual-base class ``exc`` leaves as, or ``None`` to leave it as raised."""
    if isinstance(exc, APIException):
        return None
    if isinstance(exc, KernelInvalidArguments):
        return DRFInvalidArguments.from_kernel(exc)
    if isinstance(exc, KernelNotPermitted):
        return DRFNotPermitted.from_kernel(exc)
    if isinstance(exc, KernelPrincipalUnavailable):
        return DRFPrincipalUnavailable.from_kernel(exc)
    return None
