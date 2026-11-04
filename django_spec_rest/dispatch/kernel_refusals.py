"""How the kernel route answers each refusal the kernel's ``dispatch`` raises: as a DRF exception.

Utils-shaped: ``KERNEL_REFUSALS`` is the map, ``answer_refusal`` reads it and
``answering_refusals`` applies it around a call, and the kernel route
(``dispatch/kernel_edge.py``) is their one user, so the module exports nothing
and carries no ``__all__``. Every refusal leaves as a DRF exception, so DRF's
exception handler answers it as it answers its own, and a configured
``EXCEPTION_HANDLER`` sees the classes it was written against.

One row reads the call as well as the refusal: a permission check the
dispatched spec declares, denying a caller nobody authenticated, is answered
as DRF's ``APIView.permission_denied`` answers it, so the request and the spec
the edge dispatched travel with the refusal (``RefusedCall``).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

from django_service_specs.authorization.not_permitted import NotPermitted as KernelNotPermitted
from django_service_specs.authorization.permission_check_denied import PermissionCheckDenied
from django_service_specs.authorization.principal_unavailable import (
    PrincipalUnavailable as KernelPrincipalUnavailable,
)
from django_service_specs.parameters.invalid_arguments import (
    InvalidArguments as KernelInvalidArguments,
)
from django_service_specs.services.service_error import ServiceError
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.types.dispatch_error import DispatchError
from rest_framework import status as drf_status
from rest_framework.exceptions import APIException

from django_spec_rest.service_specs.drf_invalid_arguments import DRFInvalidArguments
from django_spec_rest.service_specs.drf_not_permitted import DRFNotPermitted
from django_spec_rest.service_specs.drf_principal_unavailable import DRFPrincipalUnavailable
from django_spec_rest.service_specs.permission_denied import permission_denied
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


@dataclasses.dataclass
class RefusedCall:
    """The call a refusal came out of: its request, and the spec the edge dispatched for it.

    ``spec`` is ``None`` until the edge knows what it dispatches, which it
    learns inside the block ``answering_refusals`` guards, so the edge sets it
    there; and ``None`` for good around a call that is no dispatch of the
    edge's own, such as presenting a result, where a check's denial can only
    be another call's.
    """

    request: Any = None
    spec: Any = None


def _alone(answer: Callable[[Any], APIException]) -> Callable[[Any, RefusedCall], APIException]:
    """A row's answer that reads the refusal alone, whatever call it came out of."""
    return lambda exc, call: answer(exc)


def _check_denied(exc: PermissionCheckDenied, call: RefusedCall) -> APIException:
    """A check's denial, as DRF's ``permission_denied`` where the check is the dispatched spec's own.

    A caller nobody authenticated is then asked to (``DRFNotAuthenticated``,
    401 with the first authenticator's challenge, or 403 where it gives
    none), and any other refused with the check's message, 403, as DRF's view
    answers a permission class
    (test_an_anonymous_caller_refused's test_a_refused_caller_is_answered_as_drf_answers_it).
    A denial of another spec's check is a refused inner ``dispatch`` the
    service made, which propagates as the same class: the caller reached this
    spec, so it is the service's refusal, 403 with its message, as a bare
    ``NotPermitted`` is (test_a_refused_inner_dispatch_is_not_asked_to_sign_in).
    ``exc.spec`` is the compiled spec, so it is compared with what
    ``kernel_spec`` compiles the dispatched one to, the twin the edge
    dispatched rather than the view's declaration
    (test_a_check_s_denial_of_a_twin_the_edge_dispatched_asks_to_sign_in).

    One arc to coverage, so each conjunct is named: test_kernel_refusals'
    test_a_check_s_denial_out_of_no_dispatch_is_403 fails without the first
    (``kernel_spec(None)`` raises), and test_a_refused_inner_dispatch_is_not_asked_to_sign_in
    without the second.
    """
    if call.spec is not None and exc.spec is kernel_spec(call.spec):
        return permission_denied(call.request, exc.message)
    return DRFNotPermitted.from_kernel(exc)


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


KERNEL_REFUSALS: tuple[
    tuple[type[BaseException], Callable[[Any, RefusedCall], APIException]], ...
] = (
    # Read top to bottom, the first ``isinstance`` match winning, so each
    # subclass's row sits above its base's. Each row is held by a test in
    # tests/views/test_kernel_refusals.py asserting its own answer and that it
    # is not the answer of the row the refusal falls to with that row deleted
    # (the module docstring of the test names them).
    #
    # A DRF exception first: the dual-base ``DRFInvalidArguments`` a
    # ``SerializerValidator`` or ``SerializerPresenter`` raises is the
    # kernel's class as well, and is already DRF's answer.
    (APIException, _alone(_as_raised)),
    (KernelInvalidArguments, _alone(DRFInvalidArguments.from_kernel)),
    # A declared check's denial, above the ``NotPermitted`` it is: the one row
    # reading the call, since whether the caller is asked to sign in depends on
    # whose check denied and who the request authenticated (``_check_denied``).
    (PermissionCheckDenied, _check_denied),
    (KernelNotPermitted, _alone(DRFNotPermitted.from_kernel)),
    (KernelPrincipalUnavailable, _alone(DRFPrincipalUnavailable.from_kernel)),
    (DispatchError, _alone(_dispatch_refused)),
    # Every ``ServiceError`` is one row on purpose, answered by
    # ``map_service_error``, which is a public function of its own: ``ServiceValidationError`` 400,
    # ``ServiceNotFound`` 404, ``ActionUnavailable`` and ``ServiceConflict``
    # 409, ``AdditionalInputRequired`` 422 with its schema, any other 422. A
    # row per subclass pointing at that function would be one answer written
    # twice, and no test could hold a subclass row apart from the base row it
    # falls to, since that row would answer the same. The order of that
    # function is the mapping, so its branches are held by
    # tests/views/test_map_service_error.py, one test per branch, and what the
    # view serves for each subclass by
    # test_a_service_s_refusal_is_answered_by_map_service_error, one case per
    # subclass. The class ``AdditionalInputRequired`` answers with is the one
    # ``restore_raised_schema`` recognises, so the schema is restored on this
    # route too.
    (ServiceError, _alone(map_service_error)),
)
"""How the kernel route answers each refusal the kernel's ``dispatch`` raises, in order.

The kernel's ``unanswered_refusals`` holds it total from the suite."""


def answer_refusal(
    exc: DispatchError | ServiceError, call: RefusedCall | None = None
) -> APIException:
    """The DRF exception ``KERNEL_REFUSALS`` answers ``exc`` with: its first matching row.

    ``call`` is the call ``exc`` came out of, or none known, which answers a
    check's denial as any other ``NotPermitted``.
    """
    # ``next`` with no default: every refusal the block below catches is a
    # ``DispatchError`` or a ``ServiceError``, and both have a row.
    answer = next(answer for refusal, answer in KERNEL_REFUSALS if isinstance(exc, refusal))
    return answer(exc, call if call is not None else RefusedCall())


@contextmanager
def answering_refusals(request: Any = None) -> Generator[RefusedCall]:
    """Re-raise a kernel refusal inside the block as the DRF exception the map answers it with.

    Yields the ``RefusedCall`` the map is handed, carrying ``request``, whose
    ``spec`` the block sets once it knows what it dispatches: until it does,
    and around a block that dispatches nothing of its own, a check's denial is
    answered as any other ``NotPermitted``.

    Raised ``from`` the kernel's, so the traceback keeps where dispatch
    refused, and the exception left as it is when it is DRF's already. The
    author's own exception, where ``translate_drf_refusals`` made the refusal
    of it, is raised as it was, with the context it was raised in
    (test_the_exception_keeps_the_context_it_was_raised_in) and the cause it
    was raised from (test_the_exception_keeps_the_cause_it_was_raised_from)
    rather than the translated refusal as either. Used as a ``with`` block
    around ``await`` too.
    """
    call = RefusedCall(request)
    try:
        yield call
    except (DispatchError, ServiceError) as exc:
        answer = answer_refusal(exc, call)
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
