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

from django_spec_rest.service_specs.drf_invalid_arguments import DRFInvalidArguments
from django_spec_rest.service_specs.drf_not_permitted import DRFNotPermitted
from django_spec_rest.service_specs.drf_principal_unavailable import DRFPrincipalUnavailable
from django_spec_rest.service_specs.translate_drf_refusals import TRANSLATED_FROM
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
    """A refusal that is a DRF exception already, as the author raised it where it was translated.

    The dual-base twins a Validator or presenter raises are DRF's answer as
    they are. A refusal ``translate_drf_refusals`` made of an author's own
    carries that exception under ``TRANSLATED_FROM``, and the author's is the
    answer, so DRF's handler reads the class the author chose.
    """
    return getattr(exc, TRANSLATED_FROM, exc)


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
    # A DRF exception first: the dual-base ``DRFInvalidArguments`` a
    # ``SerializerValidator`` or ``SerializerPresenter`` raises is the
    # kernel's class as well, and is already DRF's answer.
    (APIException, _as_raised),
    (KernelInvalidArguments, DRFInvalidArguments.from_kernel),
    (KernelNotPermitted, DRFNotPermitted.from_kernel),
    (KernelPrincipalUnavailable, DRFPrincipalUnavailable.from_kernel),
    (DispatchError, _dispatch_refused),
    # Every ``ServiceError`` is one row on purpose, answered by
    # ``map_service_error``, which is the drfs answer and carries as its own
    # public function: ``ServiceValidationError`` 400,
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
    refused, and the exception left as it is when it is DRF's already. The
    author's own exception, where ``translate_drf_refusals`` made the refusal
    of it, is raised as it was, with the context it was raised in
    (test_the_exception_keeps_the_context_it_was_raised_in) and the cause it
    was raised from (test_the_exception_keeps_the_cause_it_was_raised_from)
    rather than the translated refusal as either. Used as a ``with`` block
    around ``await`` too.
    """
    try:
        yield
    except (DispatchError, ServiceError) as exc:
        answer = answer_refusal(exc)
        if answer is exc:
            raise
        if answer is getattr(exc, TRANSLATED_FROM, None):
            # Raising it here makes the translated refusal its context; the
            # context it was raised in is put back as it propagates, and its
            # cause was never touched. Held by the two tests named above, and by
            # test_a_raise_with_no_context_is_restored_with_none for the context
            # being put back to ``None`` rather than left as the refusal.
            context = answer.__context__
            try:
                raise answer
            finally:
                answer.__context__ = context
        raise answer from exc
