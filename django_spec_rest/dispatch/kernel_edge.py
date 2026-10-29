"""The DRF edge over the kernel's own ``dispatch``, for a view whose ``spec`` is a kernel spec.

Utils-shaped: the helpers here are shared by the mutation views
(``views/mutation/utils.py``), the selector views (``selectors/utils.py``) and
``as_view()``'s spec checks (``views/spec_validation.py``), and none is public
API, so the module exports nothing and carries no ``__all__``. It sits beside
``dispatch/utils.py`` rather than inside it because that module is the edge of
the drfs path, ``dispatch_spec``, and this one shares none of its compile: a
kernel spec is dispatched as declared.

What a view hands it, and what it does with each:

- **The call's context**, ``view_call_context(view, request)``, the one dict
  per request the view already builds with ``request``, ``view``, ``format``
  and ``action``. It reaches the kernel's ``dispatch`` as ``call_context`` as
  the very object, so the kernel seeds ``request`` and ``view`` from it by name
  (``CALL_SEEDS``) for every callable declaring either, and the spec's
  ``SerializerValidator`` and ``SerializerPresenter`` read both from it for
  the serializer context DRF builds. The view builds it rather than this
  module, which never imports the HTTP views for it.
- **The request's arguments**, read as the kernel reads a wire: a JSON body as
  it was sent, a form body and a query string through the kernel's
  ``flat_arguments`` and then ``coerce_flat``, and the route captures the spec
  declares as parameters, coerced the same way and over what the body or the
  query string sent (``kernel_arguments``). A capture the spec does not
  declare is no argument and stays on ``view.kwargs`` for DRF's own machinery.
- **The principal**, ``request.user``.

Two of the edge's answers are decided for every spec, and both are the
kernel's own unless stated:

- **Nothing is stripped**: a body key ``request`` or ``serializer`` that no
  field declares reaches the kernel's closed argument set and is refused there
  as "Unknown argument." under ``UNKNOWN_ARGUMENTS``, as on every other
  transport.
- **The one strip that stays**: a writable field of the spec's
  ``SerializerValidator`` named like one of the dispatcher's own seeds
  (``user``, ``result``, ``instance``, ...) or ``serializer`` is no parameter,
  because the kernel refuses a parameter a seed occupies, while a DRF
  serializer was always free to declare one. So the edge takes the field's
  value off the kernel's arguments and hands it to the serializer beside what
  the kernel hands it, the caller's checked values, the declared captures and
  ``input_data``'s, so it validates into ``data`` while every value the kernel
  checked keeps its own (``seed_named_fields``). For a single object only: a
  ``many`` spec's rows are handed to the kernel as sent, so a row's
  seed-named field is refused there as an unknown argument, and what the
  bulk path makes of it is the mutation views'.
  An ``input_data`` value for such a field never reaches the serializer: the
  kernel hands a Validator only the keys its ``parameters()`` declare, and
  the field is none of them.

Every refusal the kernel raises leaves as a DRF exception, by
``KERNEL_REFUSALS``, so DRF's exception handler answers it as it answers its
own, and a configured ``EXCEPTION_HANDLER`` sees the classes it was written
against.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from typing import Any

from django.utils.datastructures import MultiValueDict
from django_service_specs.authorization.not_permitted import NotPermitted as KernelNotPermitted
from django_service_specs.authorization.principal_unavailable import (
    PrincipalUnavailable as KernelPrincipalUnavailable,
)
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.flat.flat_arguments import flat_arguments
from django_service_specs.parameters.coerce_flat import coerce_flat
from django_service_specs.parameters.invalid_arguments import (
    InvalidArguments as KernelInvalidArguments,
)
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.services.service_error import ServiceError
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from django_service_specs.types.dispatch_error import DispatchError
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.types.unset import UNSET
from rest_framework import status as drf_status
from rest_framework.exceptions import APIException
from rest_framework.request import Request
from typing_extensions import TypeIs

from django_spec_rest.service_specs.invalid_arguments import InvalidArguments
from django_spec_rest.service_specs.not_permitted import NotPermitted
from django_spec_rest.service_specs.principal_unavailable import PrincipalUnavailable
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.service_specs.utils import (
    EDGE_CALL,
    EdgeCallState,
    describe_serializer,
    is_input,
)
from django_spec_rest.views.mutation.map_service_error import map_service_error

KernelSpec = KernelServiceSpec | KernelSelectorSpec

UNKNOWN_ARGUMENTS = UnknownArguments.REJECT
"""What the kernel route does with an argument the spec declares no parameter for.

The kernel's own default, under which every undeclared body or query key is a
``400`` "Unknown argument.". Which answer HTTP gives is an open owner question:
drfs over HTTP dispatches under ``IGNORE``, dropping such a key unseen. Both
cores pass this one value, so the decision is this line."""


def runs_on_kernel(spec: object) -> TypeIs[KernelSpec]:
    """Whether ``spec`` is a kernel spec, served by the kernel's ``dispatch`` as declared.

    The one place the two paths part: a drfs ``ServiceSpec`` or ``SelectorSpec``
    compiles to the kernel's and runs through ``dispatch_spec``, and a kernel
    spec set on a view's ``spec`` runs through ``dispatch_kernel_spec`` here.
    Asked of the spec's class, so every caller - the two dispatch functions and
    ``as_view()``'s checks - decides by the one fact. A drfs spec is no subclass
    of the kernel's, so no drfs spec answers ``True``
    (test_a_drfs_spec_does_not_run_on_the_kernel). The union is one arc to
    coverage, so each member is named: the service spec by
    test_a_kernel_service_spec_runs_on_the_kernel, the selector spec by
    test_a_kernel_selector_spec_runs_on_the_kernel.
    """
    return isinstance(spec, KernelServiceSpec | KernelSelectorSpec)


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


def _invalid_arguments(exc: KernelInvalidArguments) -> APIException:
    """DRF's ``400``, the same tree and every message's code, and a subclass's message carried."""
    twin = InvalidArguments(exc.detail)
    twin.message = exc.message
    return twin


def _not_permitted(exc: KernelNotPermitted) -> APIException:
    """DRF's ``403``, with the kernel's message."""
    return NotPermitted(exc.message)


def _principal_unavailable(exc: KernelPrincipalUnavailable) -> APIException:
    """DRF's ``403``, with the kernel's message."""
    return PrincipalUnavailable(exc.message)


def _dispatch_refused(exc: DispatchError) -> APIException:
    """A bare ``DispatchError`` as a ``400``, its sentence under ``detail``."""
    return KernelDispatchRefused(str(exc))


KERNEL_REFUSALS: tuple[tuple[type[BaseException], Callable[[Any], APIException]], ...] = (
    # Read top to bottom, the first ``isinstance`` match winning, so each
    # subclass's row sits above its base's. Each row is held by a test in
    # tests/views/test_kernel_refusals.py asserting its own answer and that it
    # is not the answer of the row the refusal falls to with that row deleted.
    #
    # A DRF exception first: the dual-base ``InvalidArguments`` a
    # ``SerializerValidator`` or ``SerializerPresenter`` raises is the
    # kernel's class as well, and is already DRF's answer.
    (APIException, _as_raised),
    (KernelInvalidArguments, _invalid_arguments),
    (KernelNotPermitted, _not_permitted),
    (KernelPrincipalUnavailable, _principal_unavailable),
    (DispatchError, _dispatch_refused),
    # Every ``ServiceError`` - ``ServiceValidationError`` 400, ``ServiceNotFound``
    # 404, ``ActionUnavailable`` and ``ServiceConflict`` 409,
    # ``AdditionalInputRequired`` 422 with its schema and any other 422 - as
    # the drfs path answers it, so the schema ``restore_raised_schema`` puts
    # back into the body is recognised on this route too.
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


def seed_named_fields(validator: Any) -> frozenset[str]:
    """The writable fields of ``validator``'s serializer that are no parameter of it.

    A ``SerializerValidator`` leaves out of ``parameters()`` a field named like
    one of the dispatcher's own seeds, the ``serializer`` it binds, and a name
    its ``excluded`` lists, because the kernel refuses a parameter a seed
    occupies. These are the names a body may still send, for the serializer
    alone. Any other Validator declares every field it takes, so it has none
    (test_another_validator_s_body_is_stripped_of_nothing).
    """
    if not isinstance(validator, SerializerValidator):
        return frozenset()
    fields = describe_serializer(validator.serializer).fields
    writable = {name for name, field in fields.items() if is_input(field)}
    return frozenset(writable.difference(validator.parameters().names()))


def kernel_arguments(
    spec: KernelSpec, *, view: Any, request: Request
) -> tuple[dict[str, Any], tuple[Any, Any] | None]:
    """The arguments a request makes for ``spec``, and the body its serializer binds, if any.

    - **A selector spec reads the query string**, through ``flat_arguments``:
      a repeated key or a comma list for an array, a blank value absent where
      the parameter cannot take ``""``, Django's ``csrfmiddlewaretoken``
      dropped, and an undeclared key kept for the closed argument set to
      refuse.
    - **A service spec reads the body**: a ``many`` spec's under its
      ``many_argument``, as a drfs ``many`` spec takes a list body; a form body
      (a ``QueryDict``) through ``flat_arguments``; a JSON object as it was
      sent, which a typed caller's values already are. A body that is no
      object is refused as a whole.
    - **The route captures the spec declares** go over either, since the
      route scopes the call and a client's value must not move it.

    Flat values, the form body's, the query string's and the captures', go
    through ``coerce_flat``, so ``?published=true`` reaches the shape check as
    ``True``; a JSON body's do not, since the client typed them, so a JSON
    ``"true"`` is a string there, as on every typed transport
    (test_a_json_body_is_not_read_as_flat_strings).

    The second value is ``(validator, held)`` where the body sends a field
    ``seed_named_fields`` names: each such field's value is taken off the
    arguments and held, and the serializer binds it beside what the kernel
    hands it (see the module docstring). Otherwise ``None``, and the serializer
    binds what the kernel hands it, its ``input_data`` provider's values merged
    in. A ``many`` spec is never held for.
    """
    parameters: Parameters = spec.parameters()
    route = {
        name: value
        for name, value in (getattr(view, "kwargs", None) or {}).items()
        if parameters.get(name) is not None
    }
    if isinstance(spec, KernelSelectorSpec):
        return coerce_flat(
            parameters, {**flat_arguments(parameters, request.query_params), **route}
        ), None
    body: Any = request.data
    if spec.many:
        return {spec.many_argument: body, **coerce_flat(parameters, route)}, None
    if isinstance(body, MultiValueDict):
        sent = coerce_flat(parameters, {**flat_arguments(parameters, body), **route})
    elif isinstance(body, Mapping):
        sent = {**body, **coerce_flat(parameters, route)}
    else:
        raise DispatchError(f"The body must be an object; got {type(body).__name__}.")
    names = seed_named_fields(spec.validator).intersection(sent)
    if not names:
        return sent, None
    # Only the held fields' values, bound with the kernel's checked arguments
    # rather than in their place (``EdgeCallState.input_beneath``), so a declared capture and
    # ``input_data`` outrank the client's value here as on every other call
    # (test_a_declared_capture_outranks_the_body_beside_a_seed_named_field,
    # test_input_data_outranks_the_body_beside_a_seed_named_field).
    held = {name: sent[name] for name in names}
    arguments = {name: value for name, value in sent.items() if name not in names}
    return arguments, (spec.validator, held)


def dispatch_kernel_spec(
    spec: KernelSpec,
    *,
    view: Any,
    request: Request,
    call_context: dict[str, Any],
    target: Any = UNSET,
) -> DispatchResult:
    """Run a kernel ``spec`` for ``request`` through the kernel's ``dispatch``.

    ``call_context`` is the request's one dict, handed to ``dispatch`` as the
    very object; ``target`` the row the view resolved, or ``UNSET`` for the
    spec's own lookup to find it. Every refusal leaves as its DRF answer
    (``KERNEL_REFUSALS``). ``adispatch_kernel_spec`` is the async twin.
    """
    with answering_refusals():
        arguments, held = kernel_arguments(spec, view=view, request=request)
        token = EDGE_CALL.set(EdgeCallState(validator_input=held, input_beneath=True))
        try:
            return dispatch(
                spec,
                principal=request.user,
                arguments=arguments,
                unknown_arguments=UNKNOWN_ARGUMENTS,
                target=target,
                call_context=call_context,
            )
        finally:
            EDGE_CALL.reset(token)


async def adispatch_kernel_spec(
    spec: KernelSpec,
    *,
    view: Any,
    request: Request,
    call_context: dict[str, Any],
    target: Any = UNSET,
) -> DispatchResult:
    """``dispatch_kernel_spec`` from async code, awaiting the kernel's ``adispatch``.

    The same arguments, the same state and the same answers; the kernel's
    thread hops run in a copy of this context, which holds the same state.
    """
    with answering_refusals():
        arguments, held = kernel_arguments(spec, view=view, request=request)
        token = EDGE_CALL.set(EdgeCallState(validator_input=held, input_beneath=True))
        try:
            return await adispatch(
                spec,
                principal=request.user,
                arguments=arguments,
                unknown_arguments=UNKNOWN_ARGUMENTS,
                target=target,
                call_context=call_context,
            )
        finally:
            EDGE_CALL.reset(token)
