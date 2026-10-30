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
  field declares reaches the kernel's closed argument set as any undeclared key
  does, and ``UNKNOWN_ARGUMENTS`` answers it: dropped under ``IGNORE``, this
  edge's policy, and "Unknown argument." under ``REJECT``.
- **The one strip that stays**: a writable field of the spec's
  ``SerializerValidator`` named like one of the dispatcher's own seeds
  (``user``, ``result``, ``instance``, ...) or ``serializer`` is no parameter,
  because the kernel refuses a parameter a seed occupies, while a DRF
  serializer was always free to declare one. So the edge takes the field's
  value off the kernel's arguments (``seed_named_fields``). For a single
  object only: a ``many`` spec's rows are handed to the kernel as sent, so a
  row's seed-named field is an unknown argument there: under ``IGNORE`` it is
  dropped, so the row is refused for the field as required or loses its value
  where the field is optional, and what the bulk path makes of it is the
  mutation views'.
- **The serializer binds the request's body**, for a single object, rather
  than the kernel's checked arguments, as DRF's serializer was always handed
  the request's data: a form body stays a ``QueryDict`` and is read as HTML
  input, and a seed-named field validates into ``data`` from it. What the edge
  put over the client's values for a field - a declared capture, a lookup read
  the query string sends, a view hook's value, ``input_data``'s answer - is
  written onto that body, and recorded as the server's value, which the
  Validator validates on its own and lays back over whatever a second route
  made of the key (``kernel_arguments``, ``SerializerValidator``). The kernel
  merges ``input_data``'s answer into its arguments alone, so the edge
  dispatches a twin of the spec whose provider puts its answer onto the body
  as it returns it, called once as the spec's own is (``recording_spec``). A
  key the provider owns and declines is absent rather than the client's, and
  one it may decline and declines stays the client's, as the kernel answers
  both for a declared field.

- **A view's ``get_service_kwargs`` outranks the Validator**, as on drfs:
  the kernel lays its ``extra_kwargs`` overlay beneath what the Validator
  computes, so the twin's ``kwargs`` seat hands the hook's values back beneath
  the spec's own provider, where they outrank a key a ``validate()`` derives
  or a ``source="*"`` serializer flattens (``recording_spec``).

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
from django.http import QueryDict
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
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.service_specs.utils import (
    EDGE_CALL,
    SERIALIZER_CONTEXT_SEED,
    EdgeCallState,
    edge_call_state,
    serializer_context,
    write_form_value,
)
from django_spec_rest.types.view_hooks import ViewHooks

UNKNOWN_ARGUMENTS = UnknownArguments.IGNORE
"""What the kernel route does with an argument the spec declares no parameter for.

``IGNORE``: an undeclared body or query key is dropped unseen, as DRF drops a
key no serializer field declares and as drfs over HTTP did, so a client sending
a whole row back (its ``id`` beside the fields it may write) is not refused.
The kernel's own default is ``REJECT``, a ``400`` "Unknown argument.", and it
stays the answer where a caller asks for it. Both cores pass this one value
(test_an_undeclared_body_key_is_dropped_by_default_on_either_core)."""


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
    query: QueryDict | None = None,
) -> tuple[dict[str, Any], tuple[Any, Any] | None]:
    """The arguments a request makes for ``spec``, and the body its serializer binds, if any.

    - **A selector spec reads the query string**, through ``flat_arguments``:
      a repeated key or a comma list for an array, a blank value absent where
      the parameter cannot take ``""``, Django's ``csrfmiddlewaretoken``
      dropped, and an undeclared key kept for the closed argument set to
      refuse. ``query`` is read in place of ``request.query_params`` where a
      caller hands one: a list view hands the query string without the keys
      its own pagination, ordering and format read, which are DRF's and no
      argument of the spec (test_kernel_edge's
      test_a_query_handed_over_is_read_in_place_of_the_request_s).
    - **A service spec reads the body**: a ``many`` spec's under its
      ``many_argument``, as a drfs ``many`` spec takes a list body; a form body
      (a ``QueryDict``) through ``flat_arguments``; a JSON object as it was
      sent, which a typed caller's values already are. A body that is no
      object is refused as a whole.
    - **A service spec's target lookup reads the route and the query
      string**: each parameter of its target selector, its ``reads`` and the
      filters its ``filter_set`` declares, is read from the query string, as
      a selector spec's are, with the route's capture over it, and a body key
      of such a name is dropped, so the client's body never chooses the row a
      write reaches, past a permission that read the query string
      (test_instance_selector_views' test_the_query_string_is_the_scope,
      test_what_the_body_sends_for_the_filter,
      test_a_target_lookups_declared_reads'
      test_a_body_value_never_chooses_the_row; the drop itself by
      test_a_body_s_filter_key_alone_scopes_nothing and
      test_a_body_value_never_reaches_the_lookup_the_route_or_the_query_string).
      A required read neither sends is refused as missing
      (test_a_lookup_read_the_route_does_not_capture_is_never_the_body_s).
      Only the lookup's keys are read there: the rest of a write's query
      string, ``?format`` among them, is DRF's and no argument
      (test_the_rest_of_a_write_s_query_string_is_no_argument).
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

    The second value is ``(validator, body)`` for a single object over a
    ``SerializerValidator``: the request's body, with what the edge put over
    the client's values for a field written onto it and each field the client
    may not fill taken off it (``_validator_body``), which the serializer binds
    in place of the kernel's arguments (see the module docstring). Otherwise
    ``None``, and the Validator takes what the kernel hands it. The kernel's
    arguments leave out each seed-named field, which is no parameter.
    """
    parameters: Parameters = spec.parameters()
    route = {
        name: value
        for name, value in (getattr(view, "kwargs", None) or {}).items()
        if parameters.get(name) is not None
    }
    if isinstance(spec, KernelSelectorSpec):
        return coerce_flat(
            parameters,
            {
                **flat_arguments(parameters, request.query_params if query is None else query),
                **route,
            },
        ), None
    body: Any = request.data
    server = dict(input_data or {})
    if spec.many:
        # A row that is no object is left as sent, for the Validator to refuse
        # (test_bulk_rows_over_http's test_a_row_that_is_no_object_is_refused_beside_view_input_data).
        if server and isinstance(body, list):
            body = [{**row, **server} if isinstance(row, Mapping) else row for row in body]
        return {spec.many_argument: body, **coerce_flat(parameters, route)}, None
    reads = _target_reads(spec)
    # The flat values that scope the call: the lookup's reads as the query
    # string sends them, then the route's captures over them.
    scope = {
        **{
            name: value
            for name, value in flat_arguments(reads, request.query_params).items()
            if name in reads.names()
        },
        **route,
    }
    if isinstance(body, MultiValueDict):
        sent = coerce_flat(
            parameters, {**_unscoped(flat_arguments(parameters, body), reads), **scope}
        )
    elif isinstance(body, Mapping):
        sent = {**_unscoped(body, reads), **coerce_flat(parameters, scope)}
    else:
        raise DispatchError(f"The body must be an object; got {type(body).__name__}.")
    sent.update(server)
    validator = spec.validator
    if not isinstance(validator, SerializerValidator):
        return sent, None
    seeded = seed_named_fields(validator)
    fields = validator.parameters().names() | seeded
    keys = provider_keys(spec.input_data)
    # A key the spec's typed ``input_data`` provider owns is the provider's
    # alone: what the client sent for it is never bound, and what the provider
    # answers is put over the body when it is called (``recording_spec``)
    # (test_an_owned_field_it_declines_is_absent_not_the_client_s).
    owned = fields.intersection(keys.filled) if keys is not None else frozenset[str]()
    # What the edge put over the client's value for a field: a declared capture
    # (test_a_declared_capture_outranks_the_body_beside_a_seed_named_field,
    # which fails without ``name in scope``) or a view hook's value
    # (test_a_hooks_none_fills_a_required_nullable_field_the_client_omitted,
    # without ``name in server``). A target lookup's read is never named like a
    # field, which the kernel refuses as two sources for one name. The owned
    # keys are left out, so a hook's value for one is no more bound than the
    # client's (test_a_hook_s_value_for_an_owned_parameter_it_declines_is_never_bound).
    put = {
        name: sent[name]
        for name in fields.intersection(sent).difference(owned)
        if name in scope or name in server
    }
    arguments = {name: value for name, value in sent.items() if name not in seeded}
    return arguments, (validator, _validator_body(body, put, owned))


def _validator_body(body: Any, put: Mapping[str, Any], dropped: frozenset[str]) -> Any:
    """The body the spec's ``SerializerValidator`` binds: the caller's, with the edge's keys.

    The whole body, as DRF's serializer was always handed the request's data,
    so a ``QueryDict`` stays one and is read as HTML input. The serializer
    binds it rather than the kernel's checked arguments, so what the edge put
    over the caller's values for a field - a declared capture, a lookup read
    the query string sends, a view hook's value - is written onto it, a list
    on a form body through ``setlist`` (``write_form_value``), and each name
    in ``dropped``, a key the ``input_data`` provider owns, is taken off it. Nothing to put or take hands the caller's
    body on as it is, uncopied, since a form's copy is a deep one.
    """
    if not put and not dropped.intersection(body):
        return body
    held = body.copy() if isinstance(body, MultiValueDict) else dict(body)
    for name in dropped:
        held.pop(name, None)
    for name, value in put.items():
        if isinstance(held, QueryDict):
            write_form_value(held, name, value)
        else:
            held[name] = value
    return held


def _target_reads(spec: KernelServiceSpec) -> Parameters:
    """The parameters of ``spec``'s target lookup, its reads and its filters, if it has one."""
    target = spec.target_selector_spec()
    if target is None:
        return Parameters()
    return target.parameters()


def _unscoped(sent: Mapping[str, Any], reads: Parameters) -> dict[str, Any]:
    """What the body sent, less a key named like one of the target lookup's ``reads``."""
    return {name: value for name, value in sent.items() if name not in reads.names()}


def dispatch_kernel_spec(
    spec: KernelSpec,
    *,
    view: Any,
    request: Request,
    call_context: dict[str, Any],
    target: Any = UNSET,
    view_hooks: ViewHooks | None = None,
    on_target: Callable[[Any], None] | None = None,
    query: QueryDict | None = None,
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

    ``query`` is the query string a selector spec reads, where the caller
    hands one in place of the request's (``kernel_arguments``).

    ``on_target`` is asked of what the spec's own lookup finds before anything
    runs on it, where ``target`` is ``UNSET``: the view's DRF object
    permissions, which ``get_object()`` asks of a row it finds and the kernel's
    lookup never would (``_resolved``).

    Every refusal leaves as its DRF answer (``KERNEL_REFUSALS``).
    ``adispatch_kernel_spec`` is the async twin.
    """
    hooks = view_hooks if view_hooks is not None else ViewHooks()
    with answering_refusals():
        state = _edge_state(
            spec, view=view, request=request, hooks=hooks, call_context=call_context
        )
        token = EDGE_CALL.set(state)
        try:
            dispatched, extra_kwargs, arguments, state.validator_input = _read_call(
                spec, view=view, request=request, hooks=hooks, query=query
            )
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
    query: QueryDict | None = None,
) -> DispatchResult:
    """``dispatch_kernel_spec`` from async code, awaiting the kernel's ``adispatch``.

    The same arguments, the same state and the same answers; the kernel's
    thread hops run in a copy of this context, which holds the same state.
    Reading the arguments parses the request's body, which reads its stream,
    describing the input serializer builds it with the call's request, whose
    ``get_fields`` may query, and the spec's own lookup queries, so each runs
    in Django's thread-sensitive executor rather than on the event loop
    (test_kernel_edge's test_the_async_core_reads_the_body_off_the_loop,
    test_the_async_core_describes_the_input_serializer_off_the_loop).
    """
    hooks = view_hooks if view_hooks is not None else ViewHooks()
    with answering_refusals():
        state = _edge_state(
            spec, view=view, request=request, hooks=hooks, call_context=call_context
        )
        token = EDGE_CALL.set(state)
        try:
            (
                dispatched,
                extra_kwargs,
                arguments,
                state.validator_input,
            ) = await sync_to_async(_read_call, thread_sensitive=True)(
                spec, view=view, request=request, hooks=hooks, query=query
            )
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


def _read_call(
    spec: KernelSpec,
    *,
    view: Any,
    request: Request,
    hooks: ViewHooks,
    query: QueryDict | None,
) -> tuple[KernelSpec, dict[str, Any], dict[str, Any], tuple[Any, Any] | None]:
    """The spec to dispatch, the overlay, the arguments and the held body of one call.

    Every read that describes the input serializer, in one sync step, so the
    async core hops to a thread once for all of it. The spec to dispatch is
    ``recording_spec``'s, built here rather than before the call's state is
    set, so the fields it records are those the serializer declares
    described with the call's request (test_kernel_edge's
    test_the_twin_records_the_fields_the_call_s_own_serializer_declares,
    test_the_async_core_builds_the_twin_off_the_loop).
    """
    extra_kwargs, pinned, server = _overlay(spec, hooks)
    # Read by the recording twin's ``kwargs`` seat, which lays them beneath the
    # spec's provider over the Validator's values (``recording_spec``).
    edge_call_state().author_values = extra_kwargs
    arguments, held = kernel_arguments(
        spec, view=view, request=request, input_data=server, query=query
    )
    if held is not None:
        # The server's value for each field it put one into, as it put it: what
        # the Validator validates for the field on its own and lays back over
        # whatever a second route made of the key, never what the field reads
        # back from the body (``SerializerValidator``), each source held by its
        # own test: test_a_view_hook_s_value_outranks_a_second_route_over_http
        # (the hooks') and test_input_data_outranks_a_second_route_over_http
        # (``input_data``'s, which ``recording_spec`` adds when it answers).
        state = edge_call_state()
        state.server_values = dict(server)
        # A ``get_service_kwargs`` value named the parameter of its key, which
        # the Validator hands the value to as well (test_server_value_the_edge_put's
        # test_a_get_service_kwargs_value_by_wire_name_reaches_the_parameter_of_that_name).
        state.author_keys = {name: name for name in pinned}
        # A key the spec's typed ``kwargs`` provider fills is never the client's,
        # whichever field its value came in through
        # (test_a_typed_provider_owning_a_wire_name's
        # test_a_declined_owned_source_hands_its_parameter_none_of_the_clients_value).
        keys = provider_keys(spec.kwargs) if isinstance(spec, KernelServiceSpec) else None
        state.provider_owned = keys.filled if keys is not None else frozenset()
    return recording_spec(spec), extra_kwargs, arguments, held


def _edge_state(
    spec: KernelSpec,
    *,
    view: Any,
    request: Request,
    hooks: ViewHooks,
    call_context: dict[str, Any],
) -> EdgeCallState:
    """The edge's state for one call of ``spec``, set before anything describes its serializer.

    Set before the arguments are read, since reading them asks
    ``spec.parameters()``, which describes the input serializer: with the
    state's ``describe_context`` it is built with the call's request and
    view, the view's input layers and the Validator's own context callable,
    as the Validator binds it, so a ``get_fields`` reading
    ``self.context["request"]`` declares the fields the call validates
    (test_service_create_view's
    test_a_request_scoped_serializer_declares_the_fields_the_call_validates;
    the layers by test_the_view_s_input_layer_reaches_the_description and
    test_the_validator_s_own_context_reaches_the_description), and is built
    once for the call. A context callable taking ``**kwargs``
    is left out of a description and never asked to rebuild one that cannot
    be built without it: ``whole_pool`` is answered ``None``, so what the
    serializer raises is raised as it is
    (test_a_serializer_its_description_cannot_build_raises_as_it_is). A
    saving, not a guard: asked again with the description's context, the
    serializer raises the same.
    """
    validator = spec.validator if isinstance(spec, KernelServiceSpec) else None
    provider = validator.serializer_context if isinstance(validator, SerializerValidator) else None
    ambient = {"request": request, "view": view}

    def describe_context(
        arguments: Any = None, *, whole_pool: bool = False
    ) -> dict[str, Any] | None:
        if whole_pool:
            return None
        return serializer_context(
            request.user,
            ambient,
            arguments,
            view_layers=hooks.input_serializer_context,
            provider=provider,
            describing=True,
            call_context=call_context,
        )

    return EdgeCallState(
        view_hooks=hooks, describe_context=describe_context, server_values_as_form=False
    )


def _overlay(
    spec: KernelSpec, hooks: ViewHooks
) -> tuple[dict[str, Any], frozenset[str], dict[str, Any]]:
    """The view's ``extra_kwargs`` for ``dispatch``'s overlay, the keys pinned out of it, and the server's input.

    A ``get_service_kwargs`` value named like one of the spec's parameters or
    seed-named fields pinned that field on drfs: the serializer validated the
    server's value, never the client's. The kernel refuses an overlay key
    naming a parameter, so the edge moves such a key into the arguments over
    the client's value, where the shape check, the permission checks and the
    Validator all read the one value, beneath the view's ``input_data``, which
    names the serializer's input on purpose
    (test_service_create_view's test_a_get_service_kwargs_value_named_like_a_field_pins_it,
    test_a_get_service_kwargs_value_named_like_a_seed_field_pins_it), and so
    is one naming a read the spec declares itself, which left in the overlay
    the kernel would refuse with a 500
    (test_a_get_service_kwargs_value_named_like_a_spec_read_pins_it). For a
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
    return overlay, frozenset(pinned), {**pinned, **(hooks.input_data or {})}


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
