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
  ``input_data`` fills such a field as it fills any other, though the kernel
  hands a Validator only the keys its ``parameters()`` declare: the edge
  dispatches a twin of the spec whose provider records its answer for these
  fields as it returns it, called once as the spec's own is, and the
  serializer binds that answer over the client's value (``recording_spec``).
  A key the provider owns and declines is absent rather than the client's,
  and one it may decline and declines stays the client's, as the kernel
  answers both for a declared field.

Every refusal the kernel raises leaves as a DRF exception, by
``KERNEL_REFUSALS`` (``dispatch/kernel_refusals.py``). The seed-named fields
and the recording twin live in the adapter, ``service_specs/seed_named_fields.py``
and ``service_specs/recording_spec.py``, since both read the
``SerializerValidator`` and the edge's call state rather than the request.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from asgiref.sync import sync_to_async
from django.utils.datastructures import MultiValueDict
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.grant import Grant
from django_service_specs.dispatch.resolve_target import resolve_target
from django_service_specs.flat.flat_arguments import flat_arguments
from django_service_specs.parameters.coerce_flat import coerce_flat
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from django_service_specs.types.dispatch_error import DispatchError
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.types.unset import UNSET
from rest_framework.request import Request
from typing_extensions import TypeIs

from django_spec_rest.dispatch.kernel_refusals import answering_refusals
from django_spec_rest.service_specs.recording_spec import KernelSpec, recording_spec
from django_spec_rest.service_specs.seed_named_fields import seed_named_fields
from django_spec_rest.service_specs.utils import (
    EDGE_CALL,
    SERIALIZER_CONTEXT_SEED,
    EdgeCallState,
)
from django_spec_rest.types.view_hooks import ViewHooks

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


def kernel_arguments(
    spec: KernelSpec,
    *,
    view: Any,
    request: Request,
    input_data: Mapping[str, Any] | None = None,
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
    - **The view's ``input_data`` hooks' values**, ``input_data`` here, go
      over the body's, and over each row that is an object for a ``many``
      spec, since a server's key beats the client's; the kernel has no
      overlay for a Validator's input, so they are arguments, beneath the
      spec's own ``input_data`` provider, which the kernel merges over them
      (test_service_create_view's test_input_data_three_tier_chain). A key
      naming no field is the closed argument set's to refuse, as the
      client's would be.

    Flat values, the form body's, the query string's and the captures', go
    through ``coerce_flat``, so ``?published=true`` reaches the shape check as
    ``True``; a JSON body's do not, since the client typed them, so a JSON
    ``"true"`` is a string there, as on every typed transport
    (test_a_json_body_is_not_read_as_flat_strings).

    The second value is ``(validator, held)`` where the body sends a field
    ``seed_named_fields`` names, or the spec's ``input_data`` may fill one:
    each such field's value the body sends is taken off the arguments and
    held, but for one the provider owns, which is the provider's alone, and
    the serializer binds what is held beside what the kernel hands it (see the
    module docstring). Otherwise ``None``, and the serializer binds what the
    kernel hands it, its ``input_data`` provider's values merged in. A
    ``many`` spec is never held for.
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
    server = dict(input_data or {})
    if spec.many:
        # A row that is no object is left as sent, for the Validator to refuse
        # (test_bulk_rows_over_http's test_a_row_that_is_no_object_is_refused_beside_view_input_data).
        if server and isinstance(body, list):
            body = [{**row, **server} if isinstance(row, Mapping) else row for row in body]
        return {spec.many_argument: body, **coerce_flat(parameters, route)}, None
    if isinstance(body, MultiValueDict):
        sent = coerce_flat(parameters, {**flat_arguments(parameters, body), **route})
    elif isinstance(body, Mapping):
        sent = {**body, **coerce_flat(parameters, route)}
    else:
        raise DispatchError(f"The body must be an object; got {type(body).__name__}.")
    sent.update(server)
    fields = seed_named_fields(spec.validator)
    names = fields.intersection(sent)
    # Skips a hold that would bind nothing: with no provider or no seed-named
    # field the held body is empty, and ``{**{}, **arguments}`` is the
    # arguments. A saving, not a check, so no test names its disjuncts.
    if not names and (spec.input_data is None or not fields):
        return sent, None
    keys = provider_keys(spec.input_data)
    owned = frozenset() if keys is None else keys.filled
    # Only the held fields' values, bound with the kernel's checked arguments
    # rather than in their place (``EdgeCallState.input_beneath``), so a declared capture and
    # ``input_data`` outrank the client's value here as on every other call
    # (test_a_declared_capture_outranks_the_body_beside_a_seed_named_field,
    # test_input_data_outranks_the_body_beside_a_seed_named_field).
    held = {name: sent[name] for name in names.difference(owned)}
    arguments = {name: value for name, value in sent.items() if name not in names}
    return arguments, (spec.validator, held)


def dispatch_kernel_spec(
    spec: KernelSpec,
    *,
    view: Any,
    request: Request,
    call_context: dict[str, Any],
    target: Any = UNSET,
    view_hooks: ViewHooks | None = None,
    on_target: Callable[[Any], None] | None = None,
) -> DispatchResult:
    """Run a kernel ``spec`` for ``request`` through the kernel's ``dispatch``.

    ``call_context`` is the request's one dict, handed to ``dispatch`` as the
    very object; ``target`` the row the view resolved, or ``UNSET`` for the
    spec's own lookup to find it.

    ``view_hooks`` is the view's hook chains, its own layers only, never the
    spec's providers, which the kernel calls itself: its ``extra_kwargs`` go
    to ``dispatch``'s overlay of that name, beneath the spec's ``kwargs``
    provider, but for a key naming a field, which pins it (``_overlay``); its
    ``input_data`` into the arguments (``kernel_arguments``); its
    ``progress`` to ``dispatch``'s; and its serializer context layers to the
    spec's ``SerializerValidator`` and ``SerializerPresenter``, the input half
    through the call's state and the output half on the result's presentation
    context (``_with_output_layers``).

    ``on_target`` is asked of what the spec's own lookup finds before anything
    runs on it, where ``target`` is ``UNSET``: the view's DRF object
    permissions, which ``get_object()`` asks of a row it finds and the kernel's
    lookup never would (``_resolved``).

    Every refusal leaves as its DRF answer (``KERNEL_REFUSALS``).
    ``adispatch_kernel_spec`` is the async twin.
    """
    hooks = view_hooks if view_hooks is not None else ViewHooks()
    with answering_refusals():
        dispatched = recording_spec(spec)
        extra_kwargs, server = _overlay(spec, hooks)
        arguments, held = kernel_arguments(spec, view=view, request=request, input_data=server)
        token = EDGE_CALL.set(
            EdgeCallState(validator_input=held, input_beneath=True, view_hooks=hooks)
        )
        try:
            found = _resolved(
                dispatched,
                principal=request.user,
                arguments=arguments,
                call_context=call_context,
                target=target,
                on_target=on_target,
            )
            if isinstance(found, DispatchResult):
                return found
            result = dispatch(
                dispatched,
                principal=request.user,
                arguments=arguments,
                grant=found[1],
                unknown_arguments=UNKNOWN_ARGUMENTS,
                progress=hooks.progress,
                target=found[0],
                extra_kwargs=extra_kwargs,
                call_context=call_context,
            )
            return _with_output_layers(result, hooks)
        finally:
            EDGE_CALL.reset(token)


async def adispatch_kernel_spec(
    spec: KernelSpec,
    *,
    view: Any,
    request: Request,
    call_context: dict[str, Any],
    target: Any = UNSET,
    view_hooks: ViewHooks | None = None,
    on_target: Callable[[Any], None] | None = None,
) -> DispatchResult:
    """``dispatch_kernel_spec`` from async code, awaiting the kernel's ``adispatch``.

    The same arguments, the same state and the same answers; the kernel's
    thread hops run in a copy of this context, which holds the same state.
    Reading the arguments parses the request's body, which reads its stream,
    and the spec's own lookup queries, so each runs in Django's
    thread-sensitive executor rather than on the event loop
    (test_kernel_edge's test_the_async_core_reads_the_body_off_the_loop).
    """
    hooks = view_hooks if view_hooks is not None else ViewHooks()
    with answering_refusals():
        dispatched = recording_spec(spec)
        extra_kwargs, server = _overlay(spec, hooks)
        arguments, held = await sync_to_async(kernel_arguments, thread_sensitive=True)(
            spec, view=view, request=request, input_data=server
        )
        token = EDGE_CALL.set(
            EdgeCallState(validator_input=held, input_beneath=True, view_hooks=hooks)
        )
        try:
            found = await sync_to_async(_resolved, thread_sensitive=True)(
                dispatched,
                principal=request.user,
                arguments=arguments,
                call_context=call_context,
                target=target,
                on_target=on_target,
            )
            if isinstance(found, DispatchResult):
                return found
            result = await adispatch(
                dispatched,
                principal=request.user,
                arguments=arguments,
                grant=found[1],
                unknown_arguments=UNKNOWN_ARGUMENTS,
                progress=hooks.progress,
                target=found[0],
                extra_kwargs=extra_kwargs,
                call_context=call_context,
            )
            return _with_output_layers(result, hooks)
        finally:
            EDGE_CALL.reset(token)


def _overlay(spec: KernelSpec, hooks: ViewHooks) -> tuple[dict[str, Any], dict[str, Any]]:
    """The view's ``extra_kwargs`` for ``dispatch``'s overlay, and the server's input for the arguments.

    A ``get_service_kwargs`` value named like one of the spec's parameters or
    seed-named fields pinned that field on drfs: the serializer validated the
    server's value, never the client's. The kernel refuses an overlay key
    naming a parameter, so the edge moves such a key into the arguments over
    the client's value, where the shape check, the permission checks and the
    Validator all read the one value, beneath the view's ``input_data``, which
    names the serializer's input on purpose
    (test_service_create_view's test_a_get_service_kwargs_value_named_like_a_field_pins_it,
    test_a_get_service_kwargs_value_named_like_a_seed_field_pins_it). For a
    ``many`` spec the pinned keys go over each row, as ``input_data``'s do,
    which is why a row's fields, the Validator's parameters, are named
    besides the spec's own (test_bulk_mutations'
    test_a_get_service_kwargs_value_pins_each_row). Every other key stays the
    overlay's.
    """
    overlay = dict(hooks.extra_kwargs or {})
    names = spec.parameters().names()
    if isinstance(spec, KernelServiceSpec) and spec.validator is not None:
        names = names | spec.validator.parameters().names() | seed_named_fields(spec.validator)
    pinned = {key: overlay.pop(key) for key in names.intersection(overlay)}
    return overlay, {**pinned, **(hooks.input_data or {})}


def _resolved(
    spec: KernelSpec,
    *,
    principal: Any,
    arguments: Mapping[str, Any],
    call_context: dict[str, Any],
    target: Any,
    on_target: Callable[[Any], None] | None,
) -> tuple[Any, Grant | None] | DispatchResult:
    """The target and grant ``dispatch`` takes for ``spec``, or a missing row's answer.

    Where ``on_target`` asks of what the spec's own lookup finds, the kernel's
    ``resolve_target`` finds it as ``dispatch`` would, refused where it would
    refuse, and ``on_target`` is asked of it before ``dispatch`` runs anything
    on it; the ``target_checked`` grant it returns, minted for the spec
    dispatched, so ``dispatch`` neither looks the target up again nor asks its
    object-level check twice. Otherwise ``target`` as given and no grant,
    ``dispatch``'s own lookup finding it where that is ``UNSET``.

    One arc to coverage, so each condition is named:
    test_service_update_view's test_a_put_s_own_row_is_asked_of_the_view_once
    (``on_target``), test_kernel_edge's
    test_with_no_on_target_the_kernel_s_own_lookup_finds_the_row (its absence:
    a caller handing none would have ``None`` called),
    test_service_update_view's test_a_row_the_view_resolved_is_looked_up_once
    (``target``: without it a row the caller handed over is looked up again),
    and test_bulk_length_over_http's test_the_kernel_s_cap_holds_on_http (the
    target selector: a ``many`` spec declares none, the kernel refusing one
    when the spec is built, and its list body is no target to resolve). The
    type is a selector spec's, which takes no target and has no target
    selector to ask; ``ty`` holds it, and no view hands a selector spec an
    ``on_target``, so no test does.
    """
    if (
        on_target is None
        or target is not UNSET
        or not isinstance(spec, KernelServiceSpec)
        or spec.target_selector_spec() is None
    ):
        return target, None
    found = resolve_target(
        spec, principal=principal, arguments=arguments, call_context=call_context
    )
    if isinstance(found, DispatchResult):
        return found
    on_target(found[0])
    return found


def _with_output_layers(result: DispatchResult, hooks: ViewHooks) -> DispatchResult:
    """``result`` carrying the view's output serializer context layers, for its presenter.

    The presenter runs when the view presents, after the call, so the view's
    lazy ``output_serializer_context`` hook travels on the result's
    presentation context under ``SERIALIZER_CONTEXT_SEED``, where
    ``SerializerPresenter`` reads it (``output_view_layers``), rather than
    through the call's pool. A result with no context, a missing row, is
    presented by no one, and one with no output layer has nothing to carry.
    One arc to coverage: the context by test_kernel_edge's
    test_a_row_the_kernel_s_lookup_misses_carries_no_output_layer. The layer
    is a saving, not a guard: hooks with no output layer carried on the
    context present as no hooks do, so no test fails without it.
    """
    if result.context is None or hooks.output_serializer_context is None:
        return result
    ambient = MappingProxyType({**result.context.ambient, SERIALIZER_CONTEXT_SEED: hooks})
    return dataclasses.replace(result, context=dataclasses.replace(result.context, ambient=ambient))
