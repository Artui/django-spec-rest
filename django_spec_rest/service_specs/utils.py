"""The serializer field walk the DRF adapter reads a serializer through.

A DRF serializer declares what it takes and what it renders in one set of
fields, so both directions are read here: what one field is, as a JSON type,
format, choices and labels, is the same whichever way it faces, and is read by
the direction-neutral helpers (``field_type``, ``field_choices``). Which fields
take part is not, so the input walk (``input_parameters``) selects its own: a
``HiddenField`` and a read-only field are no parameter, since DRF ignores what
a caller sends for either.

**The shape check runs in front of DRF**, so a type declared here is a type
the kernel refuses a call for before the serializer sees it. The rule
throughout is therefore that a declaration may be incomplete and never
stricter than the field: a field with no single JSON type of its own - a
``JSONField``, a related field, which DRF reads from a string as readily as
from a number, or a field this walk does not know - declares ``any``, which
the shape check passes on as it came.
"""

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextvars import ContextVar
from typing import Any, Final

from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet
from django.http import HttpRequest, QueryDict
from django_service_specs.output.output import OutputField
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.resolve_callable_kwargs import resolve_callable_kwargs
from django_service_specs.types.unset import UNSET
from rest_framework import ISO_8601, relations, serializers
from rest_framework.settings import api_settings
from rest_framework_dataclasses.serializers import DataclassSerializer

from django_spec_rest.service_specs.base_serializer_context import base_serializer_context
from django_spec_rest.service_specs.build_offline_context import build_offline_context
from django_spec_rest.types.json_schema_registry import JsonSchemaRegistry
from django_spec_rest.types.view_hooks import ViewHooks

MAX_SERIALIZER_APPEARANCES = 4
"""How many times one serializer class may appear on the walk's current path
before the next appearance is truncated to an open object.

A self-referential serializer is an ordinary shape and must not raise
``RecursionError`` while a transport describes it, and a serializer bounding
its own depth with a countdown is usually written three levels below its root,
so four appearances describe it as written. A serializer instantiates its
fields lazily, so an unbounded self-nesting declaration is legal to build and
renders a finite value; only a walk of its declaration would never end. The
input walk and ``SerializerPresenter``'s output walk both stop here."""

_SCALARS: tuple[tuple[type[serializers.Field], str, str | None], ...] = (
    (serializers.BooleanField, "boolean", None),
    (serializers.IntegerField, "integer", None),
    (serializers.FloatField, "number", None),
    # A decimal is a string in the decimal format, which the shape check also
    # takes as a JSON number, as DRF's field does.
    (serializers.DecimalField, "string", "decimal"),
    (serializers.DateTimeField, "string", "date-time"),
    (serializers.DateField, "string", "date"),
    # Each parses a string, in a format the kernel has no name for.
    (serializers.TimeField, "string", None),
    (serializers.DurationField, "string", None),
    (serializers.UUIDField, "string", None),
    # Email, URL, Slug, Regex and IPAddress all subclass CharField.
    (serializers.CharField, "string", None),
    # An open mapping: no ``fields``, so the shape check takes any key. HStore
    # subclasses DictField.
    (serializers.DictField, "object", None),
)
"""The fields with one JSON type of their own, and its format. DRF's scalar
fields do not subclass one another across rows, so the order matters only
within the CharField family, which ends the string rows."""


def describe_serializer(declaration: Any, validator: Any = None) -> serializers.Serializer:
    """The serializer ``declaration`` describes its fields with: the call's own, inside one.

    ``declaration`` is what a ``SerializerValidator`` takes: a ``Serializer``
    subclass, or a dataclass, which is read through a ``DataclassSerializer``
    exactly as the Validator validates it. Anything else is
    refused with ``ImproperlyConfigured``. ``validator`` is the Validator
    asking, whose ``serializer`` it is, or ``None`` for a reader that is no
    Validator's.

    Inside an edge call, the declaration of the edge's own spec, read by one
    of the edge's own Validators (``EdgeCallState.describing``), is built once
    for the call (``EdgeCallState.described``) and every such description of
    the call reads that one. It is built with the call's context - the call's
    request and view, its view's input layers and the Validator's
    ``serializer_context`` - so a ``get_fields`` reading
    ``self.context["request"]`` describes the fields the call validates with
    (test_a_live_view_scopes_the_field_to_the_caller), and with no body and no
    row, so one reading ``initial_data``, ``instance`` or ``partial`` reads
    none of the call's (the strict xfails of
    test_the_input_serializer_is_built_once_per_call). Any other Validator's,
    the same declaration's included, and every one outside a call, as a schema or a registration describes it,
    is built unbound, with the context DRF builds on HTTP with no view and no
    request: a ``get_fields`` reading ``self.context["request"]`` finds the
    key and reads ``None``, rather than raising ``KeyError`` from a schema
    while dispatch would have rendered it. What the serializer raises while it
    is described is raised as it is
    (test_a_serializer_its_description_cannot_build_raises_as_it_is).

    A spec's context callable taking ``**kwargs`` is left out of a
    description, which holds none of the call's seeds.
    """
    state = EDGE_CALL.get()
    # Only the edge's own Validators read the edge's request and view: one a
    # kernel call inside the service describes, for whichever principal, is
    # described as outside a call, another spec's
    # (test_a_kernel_call_for_another_principal_is_never_described_under_the_view_s_request)
    # and another spec's declaring the very serializer class, which the
    # edge's description, scoped to the edge's request, would otherwise answer
    # (test_a_kernel_call_of_another_spec_declaring_the_serializer_is_not_described_as_the_edge_s).
    # The edge sets ``describing`` and ``describe_context`` together, so the
    # middle condition holds no case of its own: it narrows the type. A kernel
    # call of the edge's own spec reaches the edge's own Validator, and is
    # described as the edge's: ``parameters()`` is asked with no principal
    # and no call, so nothing here tells the two apart.
    if (
        state is None
        or state.describe_context is None
        or not any(validator is own for own in state.describing)
    ):
        return bind_serializer(
            declaration, context=base_serializer_context(view=None, request=None)
        )
    described = state.described.get(declaration)
    if described is None:
        described = bind_serializer(declaration, context=state.describe_context())
        state.described[declaration] = described
    return described


def bound_instance(target: Any) -> Any:
    """The row a serializer binds for ``target``: none for a collection, which is no row to update."""
    return None if isinstance(target, QuerySet) else target


def bind_serializer(declaration: Any, **kwargs: Any) -> serializers.Serializer:
    """``declaration`` built as a serializer with ``kwargs``, or ``ImproperlyConfigured``."""
    if isinstance(declaration, type) and issubclass(declaration, serializers.Serializer):
        return declaration(**kwargs)
    if isinstance(declaration, type) and dataclasses.is_dataclass(declaration):
        return DataclassSerializer(dataclass=declaration, **kwargs)
    raise ImproperlyConfigured(
        f"{declaration!r} cannot be read as a serializer: declare a Serializer subclass or a "
        "dataclass, as SerializerValidator and SerializerPresenter take."
    )


SERIALIZER_CONTEXT_SEED = "_serializer_context_layers"

"""The key a DRF edge adds to a result's presentation context for the view's output layers.

Only ever a key of the ``ambient`` of a ``DispatchResult``'s
``PresentationContext``, added by the edge once the kernel has returned, never
a pool seed: the presenter runs when the transport renders, after the call, so
the view's ``output_serializer_context`` hook - lazy, handed the value
presented - travels with the result rather than through the call's pool, where
a callable taking a bare ``**kwargs`` would be handed it
(test_through_either_core_a_bare_kwargs_service_sees_no_edge_machinery)."""


@dataclasses.dataclass
class EdgeCallState:
    """What one call of the DRF edge carries for its own machinery, beside the kernel's pool.

    Everything here is the edge's, never an argument or a seed of the call, so
    it does not travel through the pool the kernel hands a callable taking a
    bare ``**kwargs``, which holds ``progress``, ``request``,
    ``serializer``, ``user`` and the call's extras and nothing of the edge's
    (test_through_either_core_a_bare_kwargs_service_sees_no_edge_machinery). The edge sets it in
    ``EDGE_CALL`` around the whole call, and the compiled pieces that need it
    read it from there:

    - ``author_values``: the view's ``get_service_kwargs`` values, which the
      recording twin's ``kwargs`` seat lays beneath the spec's provider
      (``recording_spec``).
    - ``view_hooks``: the view's serializer context layers, whose input half
      the Validator reads (``input_view_layers``).
    - ``validator``: the Validator of the spec the edge dispatches, the
      recording twin's, the one the view's input layers and request are for.
    - ``principal``: the principal the edge dispatches for, the request's
      user: the Validator above validating for any other is a kernel call the
      service makes, which reads none of the edge's (``_own_principal``).
    - ``validator_input``: the Validator the edge dispatches, and the body it
      binds rather than the kernel's checked arguments (``validator_input``):
      the caller's own, a ``QueryDict`` kept one, with what the edge put over
      it, as DRF's serializer has always been handed the request's data.
    - ``server_values``: the server's value for each field of that
      Validator's body the edge put one into - a view hook's or the spec's
      ``kwargs`` provider's value naming the field, and ``input_data``, a field
      named like a seed of the call included - by the name the body carries,
      as the edge put it. The Validator validates these, never what a field
      reads back from the body, and a key the Validator's ``server_owned``
      names is handed on by name only from one of them
      (test_a_server_owned_name's
      test_the_clients_value_for_an_owned_name_is_data_and_never_the_parameter
      and test_the_servers_value_for_an_owned_name_reaches_its_source). On a form body as on any other, each is validated
      as the author returned it, since the kernel's shape check read the value
      as returned (test_server_value_the_edge_put's
      test_input_data_on_a_form_body_is_taken_as_the_author_returned_it).
    - ``author_keys``: for each of those a view hook or the spec's ``kwargs``
      provider gave, the key the author gave it under, the field's wire name or
      its ``source``: the parameter the author named, which the Validator also
      hands the value to (``author_keys``).
    - ``provider_owned``: the keys the spec's typed ``kwargs`` provider is
      annotated to fill, which no client's value becomes, declined or not:
      the Validator hands the client's value for one on in ``data`` alone
      (``provider_owned``).
    - ``describing``: the edge's own ``SerializerValidator``s, the spec's and
      the recording twin's, a lenient copy for a form body, the ones
      ``describe_context`` is for: another Validator a kernel call inside the
      service describes is described as outside any call, one declaring the
      same serializer included (``describe_serializer``).
    - ``describe_context``: builds the serializer context the call's input
      serializer is described with, its request, its view, the view's input
      layers and the spec's own context callable where the description can ask
      it, with no body and no row (``describe_serializer``). Built when a
      description asks, so a call describing nothing builds none.
    - ``base_context``: the request and view a serializer of the call was last
      built for, and the baseline context the view answered for them, so the
      view is asked once for every serializer of the call
      (``call_base_context``).
    - ``context_answers``: each answer a spec's context callable gave in the
      call, by the callable and the objects it was handed, so one handed the
      same objects is asked once for every serializer of the call
      (``context_answer``).
    - ``offline_pairs``: each offline request and view built in the call for
      a principal, the arguments they carry, the shapes on the request's
      query string, the view's action and the Django request it copies, so the descriptions of one call with neither share one
      pair (``offline_pair``).
    - ``described``: the serializer the edge's own declaration is described
      with in the call for the Validators in ``describing``, built once and
      keyed by the declaration they share (``describe_serializer``).

    Mutable, so the edge can set it before the sync step it hops to a thread
    for and fill it there, and the Validator can fill it during the kernel's
    call: the thread runs in a copy of the context that holds this same object.
    """

    author_values: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    view_hooks: ViewHooks = dataclasses.field(default_factory=ViewHooks)
    validator: Any = None
    principal: Any = None
    validator_input: tuple[Any, Any] | None = None
    server_values: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    author_keys: Mapping[str, str] = dataclasses.field(default_factory=dict)
    provider_owned: frozenset[str] = frozenset()
    describing: tuple[Any, ...] = ()
    describe_context: Callable[[], dict[str, Any]] | None = None
    base_context: tuple[Any, Any, dict[str, Any]] | None = None
    context_answers: dict[tuple[Any, ...], tuple[Any, Mapping[str, Any]]] = dataclasses.field(
        default_factory=dict
    )
    offline_pairs: dict[tuple[Any, ...], tuple[Any, ...]] = dataclasses.field(default_factory=dict)
    described: dict[Any, serializers.Serializer] = dataclasses.field(default_factory=dict)


EDGE_CALL: ContextVar[EdgeCallState | None] = ContextVar("django_spec_rest_edge_call", default=None)
"""The DRF edge's state for the call in progress, or ``None`` outside one.

A context variable rather than a pool seed, so nothing the edge carries for
itself reaches a spec's callables. The kernel's sync steps run in this
context, and ``adispatch``'s thread hops run in a copy of it, which
``asgiref`` makes for every ``sync_to_async`` call."""


def edge_call_state() -> EdgeCallState:
    """The state of the edge call in progress, or an empty one outside any call."""
    return EDGE_CALL.get() or EdgeCallState()


def call_base_context(*, view: Any, request: Any) -> dict[str, Any]:
    """``base_serializer_context`` for ``view`` and ``request``, asked of the view once per call.

    The call's input serializer is described, and bound by its Validator, each
    with this baseline, and the view's ``get_serializer_context`` is asked for
    it once in the call, as DRF's view asks it once for the one serializer it
    builds. Each caller is handed its own copy, and a serializer sharing the
    call's dict has the copy laid beneath that dict (``serializer_context``).

    Held for the request and view it was asked for, and reused only for both:
    a kernel call made inside the service with another request, or another
    view, is answered for its own.
    """
    state = EDGE_CALL.get()
    held = state.base_context if state is not None else None
    if held is not None and held[0] is request and held[1] is view:
        return dict(held[2])
    context = base_serializer_context(view=view, request=request)
    if state is not None:
        state.base_context = (request, view, context)
    return dict(context)


def _context_for(call_context: dict[str, Any] | None, *, view: Any, request: Any) -> dict[str, Any]:
    """The dict a serializer of the call is built with: ``call_context`` itself, else a copy.

    ``call_context`` is the call's dict where its serializers share it, else
    ``None``. Shared, the view's ``get_serializer_context`` answer goes beneath what the
    call's context already holds, so a key the view adds is there while the
    call's own entries, and whatever a stage of the call wrote, keep one value
    for every stage (test_a_key_the_view_s_get_serializer_context_adds_is_in_the_one_dict).
    The view's hook layers are laid over this dict afterwards, all but ``format``
    (``serializer_context``).
    """
    base = call_base_context(view=view, request=request)
    if call_context is None:
        return base
    for key, value in base.items():
        call_context.setdefault(key, value)
    return call_context


def validator_input(validator: Any, arguments: Any, principal: Any) -> Any:
    """What ``validator`` binds for the call: the edge's body for it, else ``arguments``.

    Only the edge's own call reads the edge's body (``_names``), so a kernel
    call made inside the service binds its own arguments: of another spec
    (test_a_kernel_call_inside_the_service_binds_its_own_arguments), and of
    this one for another principal
    (test_a_kernel_call_of_the_view_s_own_spec_for_another_principal_binds_its_own_arguments).
    Never set for a ``many`` call, and ``validated_many`` never asks: it binds
    the rows the kernel hands it.
    """
    state = edge_call_state()
    held = state.validator_input
    # ``_names`` answers no where nothing is held, so the first condition holds
    # no case of its own: it narrows the type.
    return held[1] if held is not None and _names(state, validator, principal) else arguments


def server_values(validator: Any, principal: Any) -> Mapping[str, Any]:
    """The server's value for each field of the body ``validator`` binds the edge put one into.

    Read as ``validator_input`` reads the body: only the Validator the edge call
    names, so a kernel call made inside the service, whose client may send the
    same field, takes none of the outer call's
    (test_a_kernel_call_inside_the_service_takes_none_of_the_outer_calls_server_values,
    which fails without the identity check). Outside an edge call nothing is
    held.
    """
    state = edge_call_state()
    return state.server_values if _names(state, validator, principal) else {}


def write_form_value(body: QueryDict, name: str, value: Any) -> None:
    """Write ``value`` under ``name`` in a form body, as ``input_data`` always reached one.

    A list or tuple as the key's values (``setlist``), anything else as its one
    value (test_input_data_reaches_a_form_body_as_a_list). The edge writes the
    server's values into the body this way, and the Validator reads one back
    through its field the same way (``SerializerValidator``).
    """
    if isinstance(value, list | tuple):
        body.setlist(name, list(value))
    else:
        body[name] = value


def read_form_spellings(validator: Any, body: Any, flat: Mapping[str, Any]) -> dict[str, Any]:
    """``flat`` with each field DRF reads off a form's prefixed keys read as the field reads it.

    A form body carries a nested serializer, a dict or a list field as DRF's
    prefixed spellings of it (``v.tenant``, ``v[0]tenant``, ``tags[0]``), which
    the kernel's flat reader takes as keys no parameter declares. So each
    field the body spells that way is read by its own ``get_value``, DRF's
    ``parse_html_dict`` and ``parse_html_list``, and its spellings give way to
    that value, which the closed argument set then reads as the field's. The
    kernel route reads a form body through this
    (test_server_value_the_edge_put's
    test_input_data_is_the_value_put_over_a_prefixed_form_key_under_reject).
    Spellings the field reads nothing from are left as sent, keys no parameter
    declares (test_a_spelling_its_field_does_not_read_is_an_unknown_argument).
    """
    read = dict(flat)
    for name, field in describe_serializer(validator.serializer, validator).fields.items():
        prefixes = (f"{name}.", f"{name}[")
        spellings = [key for key in flat if key.startswith(prefixes)]
        if not spellings:
            continue
        value = field.get_value(body)
        if value is not serializers.empty:
            for key in spellings:
                del read[key]
            read[name] = value
    return read


def author_keys(validator: Any, principal: Any) -> Mapping[str, str]:
    """The key an author gave each of ``server_values`` under, read as ``server_values`` is."""
    state = edge_call_state()
    return state.author_keys if _names(state, validator, principal) else {}


def provider_owned(validator: Any, principal: Any) -> frozenset[str]:
    """The keys the spec's typed ``kwargs`` provider fills, read as ``server_values`` is.

    Only for the Validator the edge call names, so a spec the service dispatches
    through the kernel hands its own parameter of an owned name its value
    (test_a_kernel_call_inside_the_service_keeps_its_own_values, which fails
    without the identity check).
    """
    state = edge_call_state()
    return state.provider_owned if _names(state, validator, principal) else frozenset()


def _names(state: EdgeCallState, validator: Any, principal: Any) -> bool:
    """Whether ``validator``, validating for ``principal``, is the edge's own call, which holds a body.

    One arc to coverage, so each condition is named: no body held, outside
    an edge call, by test_a_provider_naming_a_field_twice's
    test_each_key_reaches_its_own_parameter_off_http; another spec's
    Validator handed the edge's very principal by
    test_a_kernel_call_of_another_spec_for_the_edge_s_own_principal_reads_none_of_the_edge_s;
    and the edge's very Validator dispatched by the service for another
    principal by
    test_a_kernel_call_of_the_view_s_own_spec_for_another_principal_binds_its_own_arguments.
    """
    held = state.validator_input
    return held is not None and held[0] is validator and _own_principal(state, principal)


def _own_principal(state: EdgeCallState, principal: Any) -> bool:
    """Whether ``principal`` is the edge call's, the very object it dispatched for.

    By identity: ``AnonymousUser`` instances are all equal, and two model
    instances of one row compare equal, so equality would take another
    caller's anonymous call, or a row fetched afresh, for the edge's. A kernel
    call the service makes for the edge's own principal, handed the very
    object, reads what the edge's call reads: nothing at the Validator tells
    the two apart. Held by
    test_a_kernel_call_of_the_view_s_own_spec_for_an_equal_principal_is_not_the_edge_s.
    """
    return principal is state.principal


def input_view_layers(validator: Any, principal: Any) -> Mapping[str, Any] | None:
    """The input half of the view hooks the edge call carries, for its own Validator alone.

    The layers answer the view's ``get_serializer_context``, so they carry the
    view's request and view. Only the Validator of the spec the edge
    dispatches reads them: a kernel call the service makes, for another
    principal or none, validates under what it would outside the view, the
    offline pair for its own principal: of another spec
    (test_a_kernel_call_for_another_principal_never_validates_under_the_view_s_request)
    and of the edge's very spec, whose Validator is the one the edge
    dispatched
    (test_a_kernel_call_of_the_view_s_own_spec_for_another_principal_validates_offline,
    which fails without the principal's check). Another spec's Validator
    handed the edge's very principal reads none either
    (test_a_kernel_call_of_another_spec_for_the_edge_s_own_principal_reads_none_of_the_edge_s,
    which fails without the Validator's).
    """
    state = edge_call_state()
    own = state.validator is validator and _own_principal(state, principal)
    return state.view_hooks.input_serializer_context if own else None


def output_view_layers(ambient: Mapping[str, Any], value: Any) -> Mapping[str, Any] | None:
    """The output half of the view hooks the call registered, resolved for ``value``, or ``None``.

    Lazy on the carrier, because a view's output hook may declare the
    ``result`` it renders, which exists only once the call has run. One branch
    to coverage, so each condition is named by the test that fails without it:
    test_the_output_callable_reaches_the_output_serializer (no hooks
    registered, a call that reached no edge).
    """
    hooks: ViewHooks | None = ambient.get(SERIALIZER_CONTEXT_SEED)
    if hooks is None or hooks.output_serializer_context is None:
        return None
    return hooks.output_serializer_context(value)


def serializer_context(
    principal: Any,
    ambient: Mapping[str, Any],
    arguments: Mapping[str, Any] | list[Any] | None,
    *,
    view_layers: Mapping[str, Any] | None = None,
    provider: Callable[..., Mapping[str, Any]] | None = None,
    extras: Mapping[str, Any] | None = None,
    describing: bool = False,
    call_context: dict[str, Any] | None = None,
    shapes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The serializer context a call's serializer is built under: four layers, later wins.

    1. **DRF's own.** The ``request`` and ``view`` the call carries are the
       serializer's own, as they are on HTTP, so a field or a ``validate()``
       reading either finds what the transport put there; a carried view
       that answers ``get_serializer_context`` supplies the whole context, as
       DRF's views do. Each is the seed the call registered, else the entry
       of that name in ``call_context``, the call's context, where a transport
       running the kernel's ``dispatch`` puts the request a run arrived on;
       ``None`` in either place is no value (``carried``). **Only when the
       call carries neither** is an offline pair built, with ``principal`` as
       the request's ``user``, ``arguments`` as its data and ``shapes``, the
       call's read-shaping arguments, as its query string, so a
       ``CurrentUserDefault`` reads the principal, a serializer reading
       ``self.context["request"]`` finds a request off HTTP too, and one
       reading ``request.query_params`` finds a ``fields`` the caller sent.
       Its view's ``action`` is the context's ``action`` (``offline_action``).
       One alone is kept as it is, beside a ``None`` for the other: pairing a
       carried request with a view built around another one would describe a
       call that never happened. A carried DRF ``Request`` is never given the
       shapes: it carries its own query string. **A carried Django request
       DRF has not wrapped**, the request a run arrived on as the kernel's
       call context holds it, is wrapped: the pair is built around a copy of
       it whose query string is the shapes, replacing its own
       (``offline_pair``), and its view stands in where the call carries
       none, so it is built around that request and carries the context's
       ``action``. A carried view is kept as it is
       (test_a_carried_view_is_kept_beside_a_wrapped_django_request).
    2. and 3. **The view's hooks**, ``view_layers``: the directional and
       per-action hooks the view resolved, one direction's half of what the
       edge carries: the input half from the call's ``EdgeCallState``, the
       output half from the result's presentation context, under
       ``SERIALIZER_CONTEXT_SEED``. Written into the call's one dict, they
       leave its ``format`` alone: that is the route's suffix, which an
       override of the view's ``get_serializer_context()`` does not displace.
    4. **The spec's own callable**, ``provider``, which has the final say. It
       is called through the kernel's declared-kwargs resolver, as every other
       spec callable is, from a pool of the call's ``arguments`` (a mapping's
       entries; a ``many`` call's rows are no names, held by
       test_a_many_spec_s_rows_validate_under_the_input_callable_once), beneath its ``ambient``
       seeds, beneath the ``request`` and ``view`` of layer 1, ``user`` (the
       principal) and ``call_context``, beneath ``extras`` (the value an
       output callable renders).
       A client's argument never stands in for one of the call's own objects
       (test_an_argument_never_stands_in_for_the_request_the_callable_declares).
       A key it answers with ``UNSET`` is declined, leaving the layer beneath,
       on every transport (test_an_unset_value_declines_the_key_and_keeps_the_layer_beneath).
       ``call_context`` is the call's own dict, so a callable reads what an
       earlier stage left there (test_the_output_callable_may_name_the_call_s_context)
       and writes to the one object the call shares. It is offered only when
       the call has one, so a description made without the call's context
       leaves a callable that declares it with no default to the serializer
       that validates, rather than asking it with a dict that serializer would
       not share.

    **Which dict the layers are written into.** Where the call's context
    carries a request DRF built, as a view hands the kernel's ``dispatch`` the
    request's one dict, every serializer of the call is built with that very
    dict and the layers are written into it, so a key one serializer's
    ``validate()`` writes is there for the service and for the output
    serializer (test_a_key_validate_writes_reaches_the_service_and_the_output_serializer,
    test_every_serializer_s_context_is_the_request_s_one_dict). The view's
    ``get_serializer_context`` answer goes beneath the entries the dict
    already holds (``_context_for``). Anywhere else each serializer is built
    with a dict of its own: for a caller that registers the request and view
    as seeds, and off a request, where the offline pair is the
    serializer's and never the transport's (``TestOffARequest``).

    One branch to coverage for the offline pair: a request alone is held
    by test_a_registered_request_alone_is_kept_beside_no_view, a view
    alone by test_a_plain_view_alone_is_kept_beside_no_request (its view
    answers no ``get_serializer_context``, so the context's ``request`` is
    what the guard leaves it, ``None``; a view that does answer it would pass
    with the guard weakened),
    and neither by test_the_serializer_context_carries_an_offline_request_for_the_principal.
    A ``None`` entry in the call's context is no value, and the pair is built
    over it (test_a_none_in_the_call_context_falls_through_to_the_offline_pair,
    which fails if the pair is skipped wherever the context names a key).
    """
    request = carried("request", ambient, call_context)
    view = carried("view", ambient, call_context)
    plain = request if isinstance(request, HttpRequest) else None
    # Three conjuncts, one branch to coverage. The request must come from the
    # call's context rather than a seed: a caller registering it as a seed
    # hands each serializer its own copy
    # (test_presented_prefers_a_registered_seed_to_the_call_context, which
    # fails without the ambient check). And it must be one DRF built, kept as it is
    # rather than replaced by the offline pair, which is never written into a
    # transport's dict: none at all is held by
    # test_no_request_stays_none_and_each_serializer_has_its_own_context, and
    # a Django request DRF has not wrapped by
    # test_a_carried_django_request_stays_the_transport_s.
    shared = "request" not in ambient and request is not None and plain is None
    # One branch to coverage: a plain request is held by
    # test_a_carried_django_request_is_wrapped_with_the_shapes_as_its_query_string,
    # which fails if it is used unwrapped, neither carried by
    # test_the_serializer_context_carries_an_offline_request_for_the_principal,
    # and a view carried alone, kept beside no request, by
    # test_a_plain_view_alone_is_kept_beside_no_request.
    if plain is not None or (request is None and view is None):
        offline = offline_pair(
            principal,
            arguments,
            shapes,
            action=offline_action(call_context),
            http_request=plain,
        )
        request = offline.request
        view = offline.view if view is None else view
    context = _context_for(call_context if shared else None, view=view, request=request)
    # ``format`` is the layer beneath's: in the call's one dict the route's
    # suffix, which the view answered when the call began. A view's hook layer
    # defaults to its ``get_serializer_context()`` answered whole, so an
    # override of that answering another ``format`` would replace the suffix
    # for every stage of the call
    # (test_the_route_s_suffix_outranks_an_overriding_get_serializer_context_for_format).
    # A dict of a serializer's own already took ``format`` from that very answer.
    context.update({key: value for key, value in (view_layers or {}).items() if key != "format"})
    if provider is not None:
        pool: dict[str, Any] = {
            **(arguments if isinstance(arguments, Mapping) else {}),
            # The edge's key for the output layers is no seed of the call, and
            # stays out of a callable's pool as every seed-free value does
            # (test_through_either_core_a_bare_kwargs_service_sees_no_edge_machinery).
            **{name: value for name, value in ambient.items() if name != SERIALIZER_CONTEXT_SEED},
            "request": request,
            "view": view,
            "user": principal,
            # Offered only when the call has one, so a description made without
            # it never asks a callable that must be handed it
            # (test_a_description_with_no_call_context_does_not_ask_a_callable_naming_it,
            # which fails if an empty dict stands in).
            **({} if call_context is None else {"call_context": call_context}),
            **(extras or {}),
        }
        # A description is made before the call's seeds are resolved and its
        # arguments routed, so a callable needing one of them is asked only by
        # the serializer that validates
        # (test_a_description_with_no_call_context_does_not_ask_a_callable_naming_it).
        if not describing or _answerable(provider, pool):
            resolved = context_answer(provider, resolve_callable_kwargs(provider, pool))
            context.update({key: value for key, value in resolved.items() if value is not UNSET})
    return context


def carried(name: str, seeds: Mapping[str, Any], call_context: Mapping[str, Any] | None) -> Any:
    """The ``request`` or ``view`` a call carries under ``name``, or ``None`` when it carries none.

    The seed of that name first, then the call's context's entry, so a
    transport's own registered object is never overridden by what a caller
    put in the context (test_presented_prefers_a_registered_seed_to_the_call_context,
    which fails with the two read the other way round). ``None`` in either place is no
    value: a DRF edge registers its ``request`` and ``view`` seeds on every
    call, ``None`` where it was handed none, and writes ``None`` into the
    context where it has nothing, and a ``None`` in one place never hides an
    object in the other, nor the offline pair ``serializer_context`` and
    ``DRFPermissionCheck`` build where both are ``None`` (test_a_seed_registered_as_none_falls_through_to_the_call_context,
    which fails if a seed answers whenever ``name`` is registered).
    """
    seeded = seeds.get(name)
    if seeded is not None:
        return seeded
    return None if call_context is None else call_context.get(name)


def offline_action(call_context: Mapping[str, Any] | None) -> str | None:
    """The ``action`` an offline view is built with: the call's context's, where it names one.

    A transport running the kernel's ``dispatch`` builds no DRF view and puts
    the operation's name in the context under ``action``, so a permission
    class or a serializer branching on ``view.action`` reads the operation
    rather than ``None``. Only a non-empty string names one; anything else
    leaves the ``None`` an offline view always had, and a view the call
    carries keeps its own. One branch to coverage, so each condition is named
    by the case that fails without it, of
    test_an_action_that_is_no_name_leaves_the_offline_view_s_as_it_was:
    ``not-a-string`` (the first) and ``empty`` (the second).
    """
    action = None if call_context is None else call_context.get("action")
    return action if isinstance(action, str) and action else None


def offline_pair(
    principal: Any,
    arguments: Any,
    shapes: Mapping[str, Any] | None = None,
    *,
    action: str | None = None,
    http_request: HttpRequest | None = None,
) -> Any:
    """``build_offline_context(principal, arguments)``, built once in an edge call for both.

    A call handed no request and no view is described several times, each
    with the offline pair its serializer is built with, so its context
    callable, handed the same pair, is asked once for them all
    (test_a_kernel_call_inside_the_service_presents_every_row_under_one_offline_request,
    which fails if no pair is reused). Reused only for the same principal
    (test_a_kernel_call_for_another_principal_is_presented_under_its_own_offline_request,
    which fails without it) and the same arguments, which the request carries
    as its data.

    ``shapes`` are the request's query string, stringified as
    ``build_offline_context(query_params=)`` stringifies a value, and so a
    third part of the key: two presentations of one call under different
    shapes are each rendered under their own
    (test_an_offline_pair_is_built_for_its_own_shapes_within_one_edge_call,
    which fails without it). None, or none sent, builds the pair a call with no
    shapes always built, and shares it. ``action`` is the view's, and the
    fourth part of the key
    (test_an_offline_pair_is_built_for_its_own_action_within_one_edge_call,
    which fails without it).

    ``http_request`` is a Django request the call carries, which DRF has not
    wrapped: the request a run arrived on, by the convention of the kernel's
    call context. The pair is then built around a copy of it, as
    ``build_offline_context(http_request=)`` builds one, so its headers and
    session are the arrived-on request's while its ``user`` is the principal.
    **The shapes replace its query string**, and an empty one stands in where
    the call sent none: that string is the endpoint's the run arrived on,
    not this operation's, so a serializer reading ``request.query_params``
    reads what the caller sent for this spec and nothing else
    (test_a_carried_django_request_under_no_shape_has_an_empty_query_string).
    It is the fifth part of the key
    (test_an_offline_pair_is_built_for_its_own_django_request_within_one_edge_call,
    which fails without it).
    """
    query_params = dict(shapes or {}) if shapes or http_request is not None else None
    state = EDGE_CALL.get()
    if state is None:
        return build_offline_context(
            principal,
            arguments,
            http_request=http_request,
            query_params=query_params,
            action=action,
        )
    key = (
        id(principal),
        id(arguments),
        id(shapes) if shapes else None,
        action,
        None if http_request is None else id(http_request),
    )
    held = state.offline_pairs.get(key)
    if held is None:
        # The objects are held beside their ids, so no id in a key is reused
        # by another object while the call lasts.
        built = build_offline_context(
            principal,
            arguments,
            http_request=http_request,
            query_params=query_params,
            action=action,
        )
        held = (principal, arguments, shapes, http_request, built)
        state.offline_pairs[key] = held
    return held[-1]


def _answerable(fn: Callable[..., Any], pool: Mapping[str, Any]) -> bool:
    """Whether a description can ask ``fn``: it names what it needs, and ``pool`` holds it.

    A callable taking ``**kwargs`` is handed the whole pool, and a
    description's pool lacks the call's seeds, so it is asked by the
    serializer that validates alone, once, as it was handed the whole pool
    once (test_a_live_view_describes_a_serializer_needing_a_whole_pool_callable,
    a strict xfail that passes without the check). A parameter
    named with no default must be in ``pool``; a ``*args`` with no default is
    not looked for there.
    """
    if takes_the_whole_pool(fn):
        return False
    parameters = inspect.signature(fn).parameters.values()
    return all(
        parameter.name in pool
        for parameter in parameters
        if parameter.default is inspect.Parameter.empty
        and parameter.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    )


def takes_the_whole_pool(fn: Callable[..., Any]) -> bool:
    """Whether ``fn`` takes ``**kwargs``, and so is handed every name of its pool."""
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in inspect.signature(fn).parameters.values()
    )


def context_answer(
    provider: Callable[..., Mapping[str, Any]], kwargs: Mapping[str, Any]
) -> Mapping[str, Any]:
    """``provider(**kwargs)``, asked once in an edge call for the same callable and objects.

    The call's input serializer is described before it validates, each with
    the spec's context callable's layer, and the callable is asked once for
    both, as DRF's view asks its context once for the one serializer it builds
    (test_a_create_view_validates_under_one_context). An answer is reused only
    for the same callable handed the same objects under the same names: a
    callable reading an argument the edge put a server's value over is asked
    again for it, and another spec's callable handed the same objects is asked
    itself (test_another_callable_handed_the_same_objects_is_asked_itself), and
    so is one handed the same object under another name
    (test_a_context_answer_is_held_for_the_names_its_objects_came_under). The
    objects are held with the answer, so none is freed and its identity reused while
    the call lasts.
    """
    state = EDGE_CALL.get()
    if state is None:
        return provider(**kwargs)
    key = (id(provider), *((name, id(kwargs[name])) for name in sorted(kwargs)))
    held = state.context_answers.get(key)
    if held is None:
        held = ((provider, dict(kwargs)), provider(**kwargs))
        state.context_answers[key] = held
    return held[1]


def is_input(field: serializers.Field) -> bool:
    """Whether a caller's value for ``field`` reaches the serializer at all.

    A read-only field is rendered and never read, and a ``HiddenField`` reads
    only its default, whatever a caller sends; so neither is a parameter, and
    under the kernel's closed argument set a caller sending either is refused
    rather than silently ignored. One branch to coverage, so each condition
    is held by its own field of
    test_a_hidden_field_and_every_read_only_field_are_not_parameters: ``who``
    (the ``HiddenField``) and the read-only rest.
    """
    return not (field.read_only or isinstance(field, serializers.HiddenField))


def input_parameters(
    serializer: serializers.Serializer,
    path: tuple[type[Any], ...] = (),
    *,
    registry: JsonSchemaRegistry | None = None,
) -> Parameters:
    """What ``serializer`` takes, as Parameters, in field order. Never queries.

    ``path`` carries the serializer classes being described, innermost last,
    which is how a recursive declaration is bounded: see
    ``MAX_SERIALIZER_APPEARANCES``. A caller leaves it empty.

    ``registry`` is the spec's ``JsonSchemaRegistry``: a field one of its
    ``fields`` rules matches, at any depth, is declared by that rule's fragment
    (``input_parameter``).
    """
    path = (*path, type(serializer))
    return Parameters(
        tuple(
            input_parameter(name, field, path, registry=registry)
            for name, field in serializer.fields.items()
            if is_input(field)
        )
    )


def input_parameter(
    name: str,
    field: serializers.Field,
    path: tuple[type[Any], ...],
    *,
    registry: JsonSchemaRegistry | None = None,
) -> Parameter:
    """One input field as a Parameter, named for the wire.

    ``required`` is the field's own, which DRF already reads from a default
    and from ``read_only``; ``nullable`` is its ``allow_null``; ``help`` its
    ``help_text``, rendered as a string in the language active now. A default
    is reported only when it is a literal (see ``literal_default``).

    A field a ``registry`` rule matches is declared by the rule's fragment
    before any built-in reading, a nested serializer's included
    (test_a_rule_wins_over_the_walk_of_a_nested_serializer). The fragment is
    split by ``fragment_keywords``; the field's own ``required`` and
    ``default`` stand, and its ``allow_null`` and ``help_text`` stand beside
    the fragment's, written over it
    (test_the_field_s_own_help_label_and_null_stand_beside_the_fragment).
    """
    common: dict[str, Any] = {
        "required": field.required,
        "nullable": field.allow_null,
        "default": literal_default(field),
        "help": str(field.help_text) if field.help_text else None,
    }
    fragment = registered_fragment(registry, field)
    if fragment is not None:
        declared = fragment_keywords(fragment, output=False)
        declared.update(
            common,
            nullable=common["nullable"] or declared.get("nullable", False),
            help=common["help"] or declared.get("help"),
        )
        return Parameter(name, declared.pop("type"), **declared)
    if isinstance(field, serializers.ListSerializer):
        # ``many=True`` on a nested serializer: an array of rows. The wrapper is
        # no serializer level of its own, so it costs no appearance.
        return Parameter(
            name,
            "array",
            items=_rows(field.child, path, registry),
            **_lengths(field),
            **common,
        )
    if isinstance(field, serializers.Serializer):
        if _truncated(field, path):
            return Parameter(name, "object", **common)
        return Parameter(
            name, "object", fields=input_parameters(field, path, registry=registry), **common
        )
    # One branch to coverage, each class held by its own tests:
    # test_a_list_field_declares_its_element_and_its_length and
    # test_a_multiple_choice_field_is_an_array_whose_elements_are_the_choices.
    if isinstance(field, serializers.ListField | serializers.MultipleChoiceField):
        return Parameter(
            name, "array", **_element(field, path, registry), **_lengths(field), **common
        )
    if isinstance(field, relations.ManyRelatedField):
        # A list of keys, each read as its related field reads one: from a
        # string as readily as from a number, so the element declares no type.
        return Parameter(name, "array", **common)
    json_type, fmt = input_type(field)
    choices = field_choices(field)
    if choices is None:
        return Parameter(name, json_type, format=fmt, **common)
    if choices.type is None:
        # No one JSON type for the values, and ``any`` lists no choices.
        return Parameter(name, "any", **common)
    return Parameter(
        name,
        choices.type,
        choices=choices.values,
        choice_labels=choices.labels,
        **common,
    )


def registered_fragment(
    registry: JsonSchemaRegistry | None, field: serializers.Field
) -> Mapping[str, Any] | None:
    """The fragment of the first ``registry.fields`` rule ``field`` is an instance of, or ``None``.

    First match wins. Held by
    test_a_rule_wins_over_the_walk_of_a_nested_serializer.
    """
    if registry is None:
        return None
    for rule_type, fragment in registry.fields:
        if isinstance(field, rule_type):
            return fragment
    return None


_JSON_TYPES: Final = frozenset({"string", "integer", "number", "boolean", "array", "object"})


def fragment_keywords(fragment: Mapping[str, Any], *, output: bool) -> dict[str, Any]:
    """A registry fragment as keyword arguments for a ``Parameter``, or an ``OutputField`` when ``output``.

    The compiled spec takes what the kernel can state of the fragment and drops
    the rest, so a rule carrying a keyword the kernel has no seat for never
    stops a spec compiling. Split in two, each class held by its tests in ``test_registered_fragments``:

    - **The keywords a field spells set it**
      (test_a_keyword_a_parameter_field_spells_sets_that_field,
      test_a_keyword_an_output_field_spells_sets_that_field): ``type``, a list
      of one type and ``"null"`` as ``nullable``; ``format``; ``enum`` as
      ``choices``, typed by its values when the fragment names no type; an
      ``items`` naming a bare type; on a ``Parameter`` the bounds
      (``minimum``, ``maximum``, ``minItems`` and ``maxItems`` as ``min_length``
      and ``max_length``) and ``description`` as ``help``; on an
      ``OutputField`` ``title`` as ``label``. The kernel's shape check then
      enforces them off HTTP.
    - **The rest is ``json_schema_extra``**, advertised and never enforced
      (test_a_keyword_no_parameter_field_spells_is_json_schema_extra,
      test_a_keyword_no_output_field_spells_is_json_schema_extra).

    **The kernel decides what is dropped**, by refusing it, so nothing here
    restates its rules: each keyword a field spells, in the order above, is
    kept only where the kernel builds the declaration with it beside those
    kept before it (test_a_bound_the_format_makes_legal_is_kept), and each
    other keyword only where the kernel takes it in ``json_schema_extra``
    (the ``kept-beside-a-refused-one`` case of
    test_what_the_kernel_refuses_is_dropped_and_the_rest_kept, whose every case
    asserts the kernel refuses what was dropped). So a keyword that contradicts
    the type goes - a ``format`` with no type, ``minimum`` on a string, a
    ``maximum`` below the ``minimum`` kept - as does a ``format`` outside the
    kernel's four (test_a_format_outside_the_kernel_s_four_is_dropped), a value
    that is not JSON, and a keyword the kernel's tables refuse in
    ``json_schema_extra`` that no field takes
    (test_every_keyword_the_kernel_refuses_is_set_or_dropped). A list or a
    mapping where the kernel takes a name is no name, and is dropped before
    the kernel sees it (``_named``, test_a_format_that_is_no_name_is_dropped).

    The result always carries ``type``, ``any`` where the fragment names none
    the kernel takes.
    """
    declared: dict[str, Any] = {}
    kind = fragment.get("type")
    # One arc to coverage; each condition is held by its case of
    # test_a_fragment_the_kernel_cannot_type_declares_any: ``two-types`` without
    # the ``"null"`` check and ``two-types-and-null`` without the length. The
    # ``isinstance`` keeps ``in`` off a string or ``None``.
    if isinstance(kind, list) and "null" in kind and len(kind) == 2:
        declared["nullable"] = True
        kind = next(member for member in kind if member != "null")
    enum = fragment.get("enum")
    # A declared type stands over the values' (the ``enum-under-its-type`` case
    # of test_a_keyword_a_parameter_field_spells_sets_that_field).
    if kind is None and isinstance(enum, list):
        kind = shared_json_type(enum)
    declared["type"] = kind if _named(kind, _JSON_TYPES) else "any"
    stated: list[tuple[str, Any]] = []
    items = fragment.get("items")
    # Only a bare element type: a Parameter's ``items`` is a type name, and an
    # element's own keywords have no seat on it. One arc to coverage, each
    # condition held by a case of test_a_fragment_s_items_saying_more_than_a_type_is_dropped:
    # the mapping by ``a-tuple-schema``, its keys by ``more-than-a-type``, and
    # the JSON type by ``a-kernel-only-type``, which the kernel itself takes.
    if (
        isinstance(items, Mapping)
        and items.keys() == {"type"}
        and _named(items["type"], _JSON_TYPES)
    ):
        stated.append(("items", items["type"]))
    # The kernel names the formats it takes and refuses the rest; only a
    # string can be asked about, as it hashes the name
    # (test_a_format_that_is_no_name_is_dropped).
    if isinstance(fragment.get("format"), str):
        stated.append(("format", fragment["format"]))
    if isinstance(enum, list):
        choices = tuple((value, str(value)) for value in enum) if output else tuple(enum)
        stated.append(("choices", choices))
    keywords = _OUTPUT_FIELDS if output else _PARAMETER_FIELDS
    stated.extend((name, fragment[keyword]) for keyword, name in keywords if keyword in fragment)
    declaration = OutputField if output else Parameter
    for name, value in stated:
        if _states(declaration, {**declared, name: value}):
            declared[name] = value
    # One keyword at a time, so the one the kernel refuses is the one dropped
    # (``kept-beside-a-refused-one`` of
    # test_what_the_kernel_refuses_is_dropped_and_the_rest_kept); the kernel
    # judges each keyword of ``json_schema_extra`` on its own.
    extra = {
        key: value
        for key, value in fragment.items()
        if _states(declaration, {**declared, "json_schema_extra": {key: value}})
    }
    if extra:
        declared["json_schema_extra"] = extra
    return declared


# The fragment keywords a field of each declaration spells beyond ``type``,
# ``format``, ``enum`` and ``items``, with the field each sets.
_PARAMETER_FIELDS: Final = (
    ("minimum", "minimum"),
    ("maximum", "maximum"),
    ("minItems", "min_length"),
    ("maxItems", "max_length"),
    ("description", "help"),
)
_OUTPUT_FIELDS: Final = (("title", "label"),)


def _states(declaration: type[Parameter] | type[OutputField], keywords: dict[str, Any]) -> bool:
    """Whether the kernel builds ``declaration`` from ``keywords``: its own refusal is the rule."""
    try:
        declaration("registered", **keywords)
    except ImproperlyConfigured:
        return False
    return True


def _named(value: Any, names: frozenset[str]) -> bool:
    """Whether ``value`` is one of ``names``; a list or a mapping, which JSON Schema allows in places, is none.

    The ``isinstance`` keeps an unhashable value out of the set lookup: held by
    the ``two-types`` case of test_a_fragment_the_kernel_cannot_type_declares_any.
    """
    return isinstance(value, str) and value in names


def shared_json_type(values: Iterable[Any]) -> str | None:
    """The one JSON type ``values`` share, or ``None`` when they share none (``_json_type``)."""
    kinds = {_json_type(value) for value in values}
    return kinds.pop() if len(kinds) == 1 else None


def field_type(field: serializers.Field) -> tuple[str, str | None]:
    """The JSON type and format of one value ``field`` takes or renders.

    Direction-neutral. A file is a ``file``; a field with no single JSON type
    of its own - a ``JSONField``, a related field, a ``ModelField``, a custom
    field - is ``any``, so nothing is claimed that the field does not hold to.
    A choice field's type is its values', read by ``field_choices``.
    """
    if isinstance(field, serializers.FileField):
        # ImageField included.
        return "file", None
    for cls, json_type, fmt in _SCALARS:
        if isinstance(field, cls):
            return json_type, fmt
    return "any", None


def input_type(field: serializers.Field) -> tuple[str, str | None]:
    """The JSON type and format of one value ``field`` takes, for the shape check in front of it.

    ``field_type``, refined by what only the input side reads, so that the
    declaration is never stricter than the field:

    - a date or date-time read in any format but ISO 8601, its own or the
      project's ``DATE_INPUT_FORMATS`` / ``DATETIME_INPUT_FORMATS``, declares
      no format, since the kernel's names for the two are ISO's and would
      refuse ``14/10/2026`` before a field reading ``%d/%m/%Y`` saw it;
    - a localized decimal declares no type, since it reads the separators of
      the language active for the call, ``1,5`` in German, as well as a JSON
      number.
    """
    json_type, fmt = field_type(field)
    formats = _input_formats(field)
    # One branch to coverage: without the ``None`` test every other field
    # raises TypeError, and without the formats test
    # test_each_field_declares_its_json_type_and_format[date] declares no format for an ISO date.
    if formats is not None and any(each != ISO_8601 for each in formats):
        return json_type, None
    # One branch to coverage: without the isinstance every field but a
    # decimal raises AttributeError, and test_each_field_declares_its_json_type_and_format[decimal]
    # holds ``localize``.
    if isinstance(field, serializers.DecimalField) and field.localize:
        return "any", None
    return json_type, fmt


def _input_formats(field: serializers.Field) -> Sequence[str] | None:
    """The formats a date or date-time field reads, as DRF reads them when it validates.

    The field's own ``input_formats``, else the project's setting, read now
    rather than when the field was built, as DRF reads it. ``None`` for any
    other field.
    """
    # DateTimeField does not subclass DateField, so the order is free.
    if isinstance(field, serializers.DateTimeField):
        return getattr(field, "input_formats", api_settings.DATETIME_INPUT_FORMATS)
    if isinstance(field, serializers.DateField):
        return getattr(field, "input_formats", api_settings.DATE_INPUT_FORMATS)
    return None


@dataclasses.dataclass(frozen=True)
class FieldChoices:
    """A choice field's values, their shared JSON type, and their labels.

    ``type`` is ``None`` when the values share no single JSON type, which a
    declaration cannot list choices for. ``labels`` are the display DRF holds
    for each value, unrendered, so a lazy translation is rendered when a schema
    is built.
    """

    type: str | None
    values: tuple[Any, ...]
    labels: tuple[tuple[Any, Any], ...]


def field_choices(field: serializers.Field) -> FieldChoices | None:
    """The choices ``field`` takes, or ``None`` for a field that is no choice field.

    DRF's ``choices`` are already flat, option groups included, keyed by the
    value as declared. A ``ChoiceField`` that allows blank also takes ``""``,
    which its choices need not list; it is added, since a declaration of
    choices claims every value accepted, and the shape check would otherwise
    refuse the blank DRF takes. ``None`` under ``allow_null`` is the
    parameter's ``nullable``, not a choice.

    DRF matches a value by its ``str``, so it also takes ``"1"`` for the choice
    ``1``; the declaration states the type the values are written in.
    """
    if not isinstance(field, serializers.ChoiceField):
        return None
    return _choices_of(field)


def _choices_of(field: serializers.ChoiceField) -> FieldChoices:
    """``field_choices`` for a field known to be a choice field."""
    labels = tuple(field.choices.items())
    values = tuple(value for value, _label in labels)
    # One branch to coverage: test_allow_blank_adds_the_empty_string_to_string_choices
    # holds the flag, and test_allow_blank_does_not_list_the_empty_string_twice
    # the membership, without which a blank choice is listed twice.
    if getattr(field, "allow_blank", False) and "" not in values:
        values = (*values, "")
    found = {_json_type(value) for value in values} or {"string"}
    # ``None`` in the set is a value of no JSON scalar type, such as a
    # ``None`` choice itself; with it, as with two types, no single type holds.
    shared = found.pop() if len(found) == 1 else None
    return FieldChoices(type=shared, values=values, labels=labels)


def literal_default(field: serializers.Field) -> Any:
    """``field``'s default as a declaration a transport could print, or the kernel's ``UNSET``.

    A callable default - a function, ``CurrentUserDefault``,
    ``CreateOnlyDefault`` - is computed per call, so no one value is its
    default. DRF's ``empty`` and the kernel's ``UNSET`` both mean no default; ``empty``
    is a class, so it is callable, and the one test answers for it too
    (test_a_required_field_is_required_and_takes_no_null). One branch to
    coverage, so each condition is held by its own test:
    test_the_unset_sentinel_as_a_default_is_no_default (``UNSET``) and
    test_a_callable_default_is_no_literal_default (the callable, ``empty``
    among them).
    """
    default: Any = field.default
    if default is UNSET or callable(default):
        return UNSET
    return default


def _json_type(value: Any) -> str | None:
    """The JSON type of a scalar value, or ``None`` for anything else.

    ``bool`` first: it subclasses ``int``, and ``true`` is not an integer on
    any wire.
    """
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return None


def _truncated(serializer: serializers.Serializer, path: tuple[type[Any], ...]) -> bool:
    return path.count(type(serializer)) >= MAX_SERIALIZER_APPEARANCES


def _rows(
    child: Any, path: tuple[type[Any], ...], registry: JsonSchemaRegistry | None
) -> Parameters | str:
    """A list's rows: the child serializer's Parameters, or an open object past the bound."""
    if _truncated(child, path):
        return "object"
    return input_parameters(child, path, registry=registry)


def _element(
    field: serializers.ListField | serializers.MultipleChoiceField,
    path: tuple[type[Any], ...],
    registry: JsonSchemaRegistry | None,
) -> dict[str, Any]:
    """What a list's element declares, as the array's own keywords.

    An array's ``items`` holds the element's JSON type, or its Parameters for
    a row; its format and choices describe each element and so sit on the
    array. Only a decimal's format is one an element takes: a list of dates
    is a list of strings, which the field decodes.
    """
    if isinstance(field, serializers.MultipleChoiceField):
        own = _choices_of(field)
        if own.type is None:
            return {}
        return {"items": own.type, "choices": own.values, "choice_labels": own.labels}
    child: Any = field.child
    fragment = registered_fragment(registry, child)
    if fragment is not None:
        # A registered element is typed by its rule, and only typed: the
        # array's own keywords describe the array, not each element
        # (test_a_registered_list_element_is_typed_by_its_rule).
        element = fragment_keywords(fragment, output=False)["type"]
        return {} if element == "any" else {"items": element}
    if isinstance(child, serializers.Serializer):
        return {"items": _rows(child, path, registry)}
    # One branch to coverage, each class held by its own case of
    # test_a_list_field_s_element_type: [list] and [list-of-rows].
    if isinstance(child, serializers.ListField | serializers.ListSerializer):
        return {"items": "array"}
    choices = field_choices(child)
    # One branch to coverage: test_a_list_of_choices_declares_them_on_the_array
    # holds the first condition, and test_a_list_of_mixed_choices_declares_none
    # the second, without which a list of mixed choices lists them on an
    # untyped array, and the shape check refuses the ``"1"`` DRF matches to ``1``.
    if choices is not None and choices.type is not None:
        return {
            "items": choices.type,
            "items_nullable": child.allow_null,
            "choices": choices.values,
            "choice_labels": choices.labels,
        }
    json_type, fmt = input_type(child)
    if json_type == "any":
        # An element of no single type, a choice field's of mixed values among
        # them: an array that declares no ``items`` takes any element already.
        return {}
    return {
        "items": json_type,
        "items_nullable": child.allow_null,
        "format": fmt if fmt == "decimal" else None,
    }


def _lengths(field: Any) -> dict[str, Any]:
    """A list's ``min_length`` and ``max_length``, with ``allow_empty=False`` a minimum of one.

    Declared so the shape check holds a list to what DRF holds it to; a list
    declaring no maximum is held to the kernel's own default by the shape
    check.
    """
    minimum: int | None = getattr(field, "min_length", None)
    if not field.allow_empty:
        minimum = max(minimum or 0, 1)
    return {"min_length": minimum or None, "max_length": getattr(field, "max_length", None)}
