from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import QueryDict
from django.utils.datastructures import MultiValueDict
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.dispatch.authorize_without_arguments import authorize_without_arguments
from django_service_specs.dispatch.call_seeds import CallSeeds
from django_service_specs.dispatch.check_call import check_call
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.grant import Grant
from django_service_specs.dispatch.resolve_target import resolve_target
from django_service_specs.dispatch.resolved_target import ResolvedTarget
from django_service_specs.flat.flat_arguments import flat_arguments
from django_service_specs.parameters.coerce_flat import coerce_flat
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from django_service_specs.types.dispatch_error import DispatchError
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.types.unset import UNSET
from django_service_specs.validation.validator_parameters import validator_parameters
from rest_framework.exceptions import APIException
from rest_framework.request import Request

from django_spec_rest.dispatch.kernel_refusals import RefusedCall, answering_refusals
from django_spec_rest.service_specs.recording_spec import KernelSpec, recording_spec
from django_spec_rest.service_specs.register_drf_row_errors import register_drf_row_errors
from django_spec_rest.service_specs.seed_named_fields import seed_named_fields
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.service_specs.utils import (
    EDGE_CALL,
    SERIALIZER_CONTEXT_SEED,
    EdgeCallState,
    edge_call_state,
    read_form_spellings,
    serializer_context,
    write_form_value,
)
from django_spec_rest.settings import lenient_json_body
from django_spec_rest.types.view_hooks import ViewHooks

# This package has no ``AppConfig`` to register from, and the edge is where a
# nested write's DRF row refusals first need the kernel to know them. Idempotent.
register_drf_row_errors()

UNKNOWN_ARGUMENTS = UnknownArguments.IGNORE
"""What the kernel route does with an argument the spec declares no parameter for.

``IGNORE``: an undeclared body or query key is dropped unseen, as DRF drops a
key no serializer field declares, so a client sending
a whole row back (its ``id`` beside the fields it may write) is not refused.
The kernel's own default is ``REJECT``, a ``400`` "Unknown argument.", and it
stays the answer where a caller asks for it. Both cores pass this one value
(test_an_undeclared_body_key_is_dropped_by_default)."""


def kernel_arguments(
    spec: KernelSpec,
    *,
    view: Any,
    request: Request,
    input_data: Mapping[str, Any] | None = None,
    query: QueryDict | None = None,
) -> tuple[dict[str, Any], tuple[Any, Any] | None]:
    """The arguments a request makes for ``spec``, and the body its serializer binds, if any."""
    call_context = edge_call_state().call_context
    parameters: Parameters = spec.parameters(call_context=call_context)
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
        if server and isinstance(body, list):
            body = [{**row, **server} if isinstance(row, Mapping) else row for row in body]
        return {spec.many_argument: body, **coerce_flat(parameters, route)}, None
    reads = _target_reads(spec)
    scope = {
        **{
            name: value
            for name, value in flat_arguments(reads, request.query_params).items()
            if name in reads.names()
        },
        **route,
    }
    if isinstance(body, MultiValueDict):
        flat = _unscoped(flat_arguments(parameters, body), reads)
        if isinstance(spec.validator, SerializerValidator):
            flat = read_form_spellings(spec.validator, body, flat, call_context=call_context)
        sent = coerce_flat(parameters, {**_checked_boxes(parameters, flat), **scope})
    elif isinstance(body, Mapping):
        sent = {**_unscoped(body, reads), **coerce_flat(parameters, scope)}
    else:
        raise DispatchError(f"The body must be an object; got {type(body).__name__}.")
    sent.update(server)
    validator = spec.validator
    if not isinstance(validator, SerializerValidator):
        return sent, None
    seeded = seed_named_fields(validator, call_context=call_context)
    fields = validator.parameters(call_context=call_context).names() | seeded
    keys = provider_keys(spec.input_data)
    owned = fields.intersection(keys.filled) if keys is not None else frozenset[str]()
    put = {
        name: sent[name]
        for name in fields.intersection(sent).difference(owned)
        if name in scope or name in server
    }
    arguments = {name: value for name, value in sent.items() if name not in seeded}
    return arguments, (validator, _validator_body(body, put, owned))


def _validator_body(body: Any, put: Mapping[str, Any], dropped: frozenset[str]) -> Any:
    """The body the spec's ``SerializerValidator`` binds: the caller's, with the edge's keys."""
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


def _checked_boxes(parameters: Parameters, flat: Mapping[str, Any]) -> dict[str, Any]:
    """A form body's flat values, with a checked checkbox's ``"on"`` read as ``True``."""
    read: dict[str, Any] = {}
    for name, value in flat.items():
        param = parameters.get(name)
        if param is None:
            read[name] = value
        elif param.type == "boolean":
            read[name] = True if value == "on" else value
        elif param.items == "boolean":
            read[name] = [True if element == "on" else element for element in value]
        else:
            read[name] = value
    return read


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
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
) -> DispatchResult:
    """Run a kernel ``spec`` for ``request`` through the kernel's ``dispatch``."""
    hooks = view_hooks if view_hooks is not None else ViewHooks()
    with answering_refusals(request) as refused:
        state = _edge_state(
            spec, view=view, request=request, hooks=hooks, call_context=call_context
        )
        token = EDGE_CALL.set(state)
        try:
            dispatched, extra_kwargs, arguments, state.validator_input = _read_call(
                spec,
                view=view,
                request=request,
                hooks=hooks,
                query=query,
                refused=refused,
                pool_seeds=pool_seeds,
            )
            grant, seeds = _admitted(
                dispatched,
                principal=request.user,
                arguments=arguments,
                call_context=call_context,
                pool_seeds=pool_seeds,
            )
            found = _resolved(
                dispatched,
                principal=request.user,
                arguments=arguments,
                call_context=call_context,
                target=target,
                on_target=on_target,
                pool_seeds=pool_seeds,
                grant=grant,
                seeds=seeds,
            )
            if isinstance(found, DispatchResult):
                return found
            result = dispatch(
                dispatched,
                principal=request.user,
                arguments=arguments,
                grant=found[1],
                seeds=found.seeds if isinstance(found, ResolvedTarget) else seeds,
                pool_seeds=pool_seeds,
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
    refused: RefusedCall,
    pool_seeds: PoolSeeds,
) -> tuple[KernelSpec, dict[str, Any], dict[str, Any], tuple[Any, Any] | None]:
    """The spec to dispatch, the overlay, the arguments and the held body of one call."""
    form_body = _is_form_body(spec, request=request, refused=refused, pool_seeds=pool_seeds)
    extra_kwargs, pinned, server = _overlay(spec, hooks)
    edge_call_state().author_values = extra_kwargs
    dispatched = recording_spec(spec, lenient=form_body or _lenient_json_body(view))
    refused.spec = dispatched
    state = edge_call_state()
    state.validator = getattr(dispatched, "validator", None)
    if isinstance(state.validator, SerializerValidator):
        state.describing = (*state.describing, state.validator)
    try:
        arguments, held = kernel_arguments(
            dispatched, view=view, request=request, input_data=server, query=query
        )
    except DispatchError:
        judge_without_arguments(
            dispatched,
            principal=request.user,
            call_context=state.call_context,
            pool_seeds=pool_seeds,
        )
        raise
    if held is not None:
        state.server_values = dict(server)
        state.author_keys = {name: name for name in pinned}
        keys = provider_keys(spec.kwargs) if isinstance(spec, KernelServiceSpec) else None
        state.provider_owned = keys.filled if keys is not None else frozenset()
    return dispatched, extra_kwargs, arguments, held


def _lenient_json_body(view: Any) -> bool:
    """Whether ``view`` has its serializer alone answer a JSON body: its own word, else the project's."""
    own = getattr(view, "lenient_json_body", None)
    return lenient_json_body() if own is None else own


def _is_form_body(
    spec: KernelSpec, *, request: Request, refused: RefusedCall, pool_seeds: PoolSeeds
) -> bool:
    """Whether DRF parsed the request's body as a form: the call's first read of it."""
    try:
        return isinstance(request.data, MultiValueDict)
    except Exception:
        refused.spec = spec
        judge_without_arguments(
            spec,
            principal=request.user,
            call_context=edge_call_state().call_context,
            pool_seeds=pool_seeds,
        )
        raise


def _edge_state(
    spec: KernelSpec,
    *,
    view: Any,
    request: Request,
    hooks: ViewHooks,
    call_context: dict[str, Any],
) -> EdgeCallState:
    """The edge's state for one call of ``spec``, set before anything describes its serializer."""
    validator = spec.validator if isinstance(spec, KernelServiceSpec) else None
    provider = validator.serializer_context if isinstance(validator, SerializerValidator) else None
    ambient = {"request": request, "view": view}

    def describe_context() -> dict[str, Any]:
        return serializer_context(
            request.user,
            ambient,
            None,
            view_layers=hooks.input_serializer_context,
            provider=provider,
            describing=True,
            call_context=call_context,
        )

    return EdgeCallState(
        call_context=call_context,
        view_hooks=hooks,
        principal=request.user,
        describing=(validator,) if isinstance(validator, SerializerValidator) else (),
        describe_context=describe_context,
    )


def _overlay(
    spec: KernelSpec, hooks: ViewHooks
) -> tuple[dict[str, Any], frozenset[str], dict[str, Any]]:
    """The view's ``extra_kwargs`` for ``dispatch``'s overlay, the keys pinned out of it, and the server's input."""
    overlay = dict(hooks.extra_kwargs or {})
    call_context = edge_call_state().call_context
    names = spec.parameters(call_context=call_context).names()
    if isinstance(spec, KernelServiceSpec) and spec.validator is not None:
        validator = spec.validator
        rows = validator_parameters(validator, call_context=call_context)
        names = names | rows.names() | seed_named_fields(validator, call_context=call_context)
    pinned = {key: overlay.pop(key) for key in names.intersection(overlay)}
    return overlay, frozenset(pinned), {**pinned, **(hooks.input_data or {})}


_DENIALS = (NotPermitted, PrincipalUnavailable)
"""The kernel's two ways of refusing the caller rather than the call: the edge answers them first."""

_RAISED_REFUSALS = (PermissionDenied, APIException)
"""What a check may raise to refuse rather than answer ``False``: Django's
``PermissionDenied`` and DRF's exceptions, which the view's exception handler
answers. Raised on no arguments they refuse as a ``False`` does, never read
as a check that cannot answer without them
(test_a_check_raising_a_refusal_refuses_whatever_the_body)."""


def _admitted(
    spec: KernelSpec,
    *,
    principal: Any,
    arguments: Mapping[str, Any],
    call_context: dict[str, Any],
    pool_seeds: PoolSeeds,
) -> tuple[Grant | None, CallSeeds | None]:
    """Ask ``spec``'s class-level checks of the call before its arguments' shape is told."""
    try:
        checked = check_call(
            spec,
            principal=principal,
            arguments=arguments,
            pool_seeds=pool_seeds,
            unknown_arguments=UNKNOWN_ARGUMENTS,
            call_context=call_context,
        )
    except InvalidArguments as refusal:
        if not refusal.after_authorize:
            judge_without_arguments(
                spec, principal=principal, call_context=call_context, pool_seeds=pool_seeds
            )
        return None, None
    return checked[1], checked.seeds


def judge_without_arguments(
    spec: KernelSpec,
    *,
    principal: Any,
    call_context: dict[str, Any] | None,
    pool_seeds: PoolSeeds,
) -> None:
    """Raise the denial ``spec``'s checks give ``principal`` asked with no arguments, if they give one."""
    try:
        authorize_without_arguments(
            spec, principal, call_context=call_context, pool_seeds=pool_seeds
        )
    except (*_DENIALS, *_RAISED_REFUSALS, ImproperlyConfigured):
        raise
    except Exception:  # noqa: BLE001 - a check that cannot answer without its arguments
        return


def _resolved(
    spec: KernelSpec,
    *,
    principal: Any,
    arguments: Mapping[str, Any],
    call_context: dict[str, Any],
    target: Any,
    on_target: Callable[[Any], None] | None,
    pool_seeds: PoolSeeds,
    grant: Grant | None,
    seeds: CallSeeds | None,
) -> ResolvedTarget | tuple[Any, Grant | None] | DispatchResult:
    """The target and grant ``dispatch`` takes for ``spec``, or a missing row's answer."""
    if (
        on_target is None
        or target is not UNSET
        or not isinstance(spec, KernelServiceSpec)
        or spec.target_selector_spec() is None
    ):
        return target, grant
    found = resolve_target(
        spec,
        principal=principal,
        arguments=arguments,
        grant=grant,
        call_context=call_context,
        pool_seeds=pool_seeds,
        seeds=seeds,
    )
    if isinstance(found, DispatchResult):
        return found
    on_target(found[0])
    return found


def _with_output_layers(result: DispatchResult, hooks: ViewHooks) -> DispatchResult:
    """``result`` carrying the view's output serializer context layers, for its presenter."""
    if result.context is None or hooks.output_serializer_context is None:
        return result
    ambient = MappingProxyType({**result.context.ambient, SERIALIZER_CONTEXT_SEED: hooks})
    return dataclasses.replace(result, context=dataclasses.replace(result.context, ambient=ambient))
