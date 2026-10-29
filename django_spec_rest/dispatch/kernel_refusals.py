"""How the kernel route answers each refusal the kernel's ``dispatch`` raises: as a DRF exception.

Utils-shaped: ``KERNEL_REFUSALS`` is the map, ``answer_refusal`` reads it and
``answering_refusals`` applies it around a call, and the kernel route
(``dispatch/kernel_edge.py``) is their one user, so the module exports nothing
and carries no ``__all__``. Every refusal leaves as a DRF exception, so DRF's
exception handler answers it as it answers its own, and a configured
``EXCEPTION_HANDLER`` sees the classes it was written against.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

from django_service_specs.authorization.not_permitted import NotPermitted as KernelNotPermitted
from django_service_specs.authorization.principal_unavailable import (
    PrincipalUnavailable as KernelPrincipalUnavailable,
)
from django_service_specs.parameters.invalid_arguments import (
    InvalidArguments as KernelInvalidArguments,
)
from django_service_specs.services.service_error import ServiceError
from django_service_specs.types.dispatch_error import DispatchError
from rest_framework import status as drf_status
from rest_framework.exceptions import APIException

from django_spec_rest.service_specs.invalid_arguments import InvalidArguments
from django_spec_rest.service_specs.not_permitted import NotPermitted
from django_spec_rest.service_specs.principal_unavailable import PrincipalUnavailable
from django_spec_rest.views.mutation.map_service_error import map_service_error


class KernelDispatchRefused(APIException):
    """A bare ``DispatchError`` the kernel route refuses a call with: ``400``, ``{"detail": ...}``.

    The kernel raises no ``DispatchError`` bare, but a project's own code may,
    and every other transport answers one as refused input: the kernel's HTTP
    route ``400``, its CLI ``INVALID_ARGUMENTS``, django-spec-mcp the
    validation ``isError``. So it is a client error here too, carrying its
    sentence as DRF carries every other non-field refusal, under ``detail``.
    """

    status_code = drf_status.HTTP_400_BAD_REQUEST
    default_detail = "The request was refused."
    default_code = "invalid"


def _as_raised(exc: Any) -> APIException:
    """A refusal that is a DRF exception already: the dual-base twins a Validator or presenter raises."""
    return exc


def _dispatch_refused(exc: DispatchError) -> APIException:
    """A bare ``DispatchError`` as a ``400``, its sentence under ``detail``."""
    return KernelDispatchRefused(str(exc))


KERNEL_REFUSALS: tuple[tuple[type[BaseException], Callable[[Any], APIException]], ...] = (
    # Read top to bottom, the first ``isinstance`` match winning, so each
    # subclass's row sits above its base's. Each row is held by a test in
    # tests/views/test_kernel_refusals.py asserting its own answer and that it
    # is not the answer of the row the refusal falls to with that row deleted
    # (the module docstring of the test names them).
    #
    # A DRF exception first: the dual-base ``InvalidArguments`` a
    # ``SerializerValidator`` or ``SerializerPresenter`` raises is the
    # kernel's class as well, and is already DRF's answer.
    (APIException, _as_raised),
    (KernelInvalidArguments, InvalidArguments.from_kernel),
    (KernelNotPermitted, NotPermitted.from_kernel),
    (KernelPrincipalUnavailable, PrincipalUnavailable.from_kernel),
    (DispatchError, _dispatch_refused),
    # Every ``ServiceError`` is one row on purpose, answered by
    # ``map_service_error``, which is the drfs answer and carries as its own
    # public function (spec-twins reads it): ``ServiceValidationError`` 400,
    # ``ServiceNotFound`` 404, ``ActionUnavailable`` and ``ServiceConflict``
    # 409, ``AdditionalInputRequired`` 422 with its schema, any other 422. A
    # row per subclass pointing at that function would be one answer written
    # twice, and no test could hold a subclass row apart from the base row it
    # falls to, since that row would answer the same. The order of that
    # function is the mapping, so its branches are held by
    # tests/views/test_map_service_error.py, one test per branch, and what the
    # view serves for each subclass by
    # test_a_service_s_refusal_is_answered_as_on_the_drfs_path, one case per
    # subclass. The class ``AdditionalInputRequired`` answers with is the one
    # ``restore_raised_schema`` recognises, so the schema is restored on this
    # route too.
    (ServiceError, map_service_error),
)
"""How the kernel route answers each refusal the kernel's ``dispatch`` raises, in order.

The kernel's ``unanswered_refusals`` holds it total from the suite."""


def answer_refusal(exc: DispatchError | ServiceError) -> APIException:
    """The DRF exception ``KERNEL_REFUSALS`` answers ``exc`` with: its first matching row."""
    # ``next`` with no default: every refusal the block below catches is a
    # ``DispatchError`` or a ``ServiceError``, and both have a row.
    answer = next(answer for refusal, answer in KERNEL_REFUSALS if isinstance(exc, refusal))
    return answer(exc)


@contextmanager
def answering_refusals() -> Generator[None]:
    """Re-raise a kernel refusal inside the block as the DRF exception the map answers it with.

    Raised ``from`` the kernel's, so the traceback keeps where dispatch
    refused, and the exception left as it is when it is DRF's already. Used as
    a ``with`` block around ``await`` too.
    """
    try:
        yield
    except (DispatchError, ServiceError) as exc:
        answer = answer_refusal(exc)
        if answer is exc:
            raise
        raise answer from exc
