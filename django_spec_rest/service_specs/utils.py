from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextvars import ContextVar
from typing import Any, Final

from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet
from django.http import HttpRequest, QueryDict
from django_service_specs import TRANSPORT_KEY
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


def describe_serializer(
    declaration: Any, validator: Any = None, *, call_context: dict[str, Any] | None = None
) -> serializers.Serializer:
    """The serializer ``declaration`` describes its fields with: the call's own, inside one."""
    state = EDGE_CALL.get()
    if (
        state is None
        or state.describe_context is None
        or not any(validator is own for own in state.describing)
        or call_context is not state.call_context
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
    """The row a serializer binds for ``target``: none for a collection, no row to update."""
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
(test_a_bare_kwargs_service_sees_no_edge_machinery)."""


@dataclasses.dataclass
class EdgeCallState:
    """What one call of the DRF edge carries for its own machinery, beside the kernel's pool."""

    author_values: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    view_hooks: ViewHooks = dataclasses.field(default_factory=ViewHooks)
    validator: Any = None
    principal: Any = None
    validator_input: tuple[Any, Any] | None = None
    server_values: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    author_keys: Mapping[str, str] = dataclasses.field(default_factory=dict)
    provider_owned: frozenset[str] = frozenset()
    call_context: dict[str, Any] | None = None
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
    """``base_serializer_context`` for ``view`` and ``request``, asked of the view once per call."""
    state = EDGE_CALL.get()
    held = state.base_context if state is not None else None
    if held is not None and held[0] is request and held[1] is view:
        return dict(held[2])
    context = base_serializer_context(view=view, request=request)
    if state is not None:
        state.base_context = (request, view, context)
    return dict(context)


def _context_for(call_context: dict[str, Any] | None, *, view: Any, request: Any) -> dict[str, Any]:
    """The dict a serializer of the call is built with: ``call_context`` itself, else a copy."""
    base = call_base_context(view=view, request=request)
    if call_context is None:
        return base
    for key, value in base.items():
        call_context.setdefault(key, value)
    return call_context


def validator_input(validator: Any, arguments: Any, principal: Any) -> Any:
    """What ``validator`` binds for the call: the edge's body for it, else ``arguments``."""
    state = edge_call_state()
    held = state.validator_input
    return held[1] if held is not None and _names(state, validator, principal) else arguments


def server_values(validator: Any, principal: Any) -> Mapping[str, Any]:
    """The server's value for each field of the body ``validator`` binds the edge put one into."""
    state = edge_call_state()
    return state.server_values if _names(state, validator, principal) else {}


def write_form_value(body: QueryDict, name: str, value: Any) -> None:
    """Write ``value`` under ``name`` in a form body, as ``input_data`` always reached one."""
    if isinstance(value, list | tuple):
        body.setlist(name, list(value))
    else:
        body[name] = value


def read_form_spellings(
    validator: Any,
    body: Any,
    flat: Mapping[str, Any],
    *,
    call_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``flat`` with each field DRF reads off a form's prefixed keys read as the field reads it."""
    read = dict(flat)
    for name, field in describe_serializer(
        validator.serializer, validator, call_context=call_context
    ).fields.items():
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
    """The keys the spec's typed ``kwargs`` provider fills, read as ``server_values`` is."""
    state = edge_call_state()
    return state.provider_owned if _names(state, validator, principal) else frozenset()


def _names(state: EdgeCallState, validator: Any, principal: Any) -> bool:
    """Whether ``validator`` for ``principal`` is the edge's own call, which holds a body."""
    held = state.validator_input
    return held is not None and held[0] is validator and _own_principal(state, principal)


def _own_principal(state: EdgeCallState, principal: Any) -> bool:
    """Whether ``principal`` is the edge call's, the very object it dispatched for."""
    return principal is state.principal


def input_view_layers(validator: Any, principal: Any) -> Mapping[str, Any] | None:
    """The input half of the view hooks the edge call carries, for its own Validator alone."""
    state = edge_call_state()
    own = state.validator is validator and _own_principal(state, principal)
    return state.view_hooks.input_serializer_context if own else None


def output_view_layers(ambient: Mapping[str, Any], value: Any) -> Mapping[str, Any] | None:
    """The output half of the view hooks the call registered, for ``value``, or ``None``."""
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
    """The serializer context a call's serializer is built under: four layers, later wins."""
    request = carried("request", ambient, call_context)
    view = carried("view", ambient, call_context)
    plain = request if isinstance(request, HttpRequest) else None
    shared = "request" not in ambient and request is not None and plain is None
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
    context.update(
        {
            key: value
            for key, value in (view_layers or {}).items()
            if key != "format" and not (shared and key == TRANSPORT_KEY)
        }
    )
    if provider is not None:
        pool: dict[str, Any] = {
            **(arguments if isinstance(arguments, Mapping) else {}),
            **{name: value for name, value in ambient.items() if name != SERIALIZER_CONTEXT_SEED},
            "request": request,
            "view": view,
            "user": principal,
            **({} if call_context is None else {"call_context": call_context}),
            **(extras or {}),
        }
        if not describing or _answerable(provider, pool):
            resolved = context_answer(provider, resolve_callable_kwargs(provider, pool))
            context.update(
                {
                    key: value
                    for key, value in resolved.items()
                    if value is not UNSET and not (shared and key == TRANSPORT_KEY)
                }
            )
    return context


def carried(name: str, seeds: Mapping[str, Any], call_context: Mapping[str, Any] | None) -> Any:
    """The ``request`` or ``view`` a call carries as ``name``, else ``None``."""
    seeded = seeds.get(name)
    if seeded is not None:
        return seeded
    return None if call_context is None else call_context.get(name)


def offline_action(call_context: Mapping[str, Any] | None) -> str | None:
    """The ``action`` an offline view is built with: the call's context's, where it names one."""
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
    """``build_offline_context(principal, arguments)``, built once in an edge call for both."""
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
    """Whether a description can ask ``fn``: it names what it needs, and ``pool`` holds it."""
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
    """``provider(**kwargs)``, asked once in an edge call for the same callable and objects."""
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
    """Whether a caller's value for ``field`` reaches the serializer at all."""
    return not (field.read_only or isinstance(field, serializers.HiddenField))


def input_parameters(
    serializer: serializers.Serializer,
    path: tuple[type[Any], ...] = (),
    *,
    registry: JsonSchemaRegistry | None = None,
) -> Parameters:
    """What ``serializer`` takes, as Parameters, in field order."""
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
    """One input field as a Parameter, named for the wire."""
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
    if isinstance(field, serializers.ListField | serializers.MultipleChoiceField):
        return Parameter(
            name, "array", **_element(field, path, registry), **_lengths(field), **common
        )
    if isinstance(field, relations.ManyRelatedField):
        return Parameter(name, "array", **common)
    json_type, fmt = input_type(field)
    choices = field_choices(field)
    if choices is None:
        return Parameter(name, json_type, format=fmt, **common)
    if choices.type is None:
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
    """Fragment of the first ``registry.fields`` rule ``field`` is an instance of, or ``None``."""
    if registry is None:
        return None
    for rule_type, fragment in registry.fields:
        if isinstance(field, rule_type):
            return fragment
    return None


_JSON_TYPES: Final = frozenset({"string", "integer", "number", "boolean", "array", "object"})


def fragment_keywords(fragment: Mapping[str, Any], *, output: bool) -> dict[str, Any]:
    """A registry fragment as keywords for a ``Parameter``, or an ``OutputField`` if ``output``."""
    declared: dict[str, Any] = {}
    kind = fragment.get("type")
    if isinstance(kind, list) and "null" in kind and len(kind) == 2:
        declared["nullable"] = True
        kind = next(member for member in kind if member != "null")
    enum = fragment.get("enum")
    if kind is None and isinstance(enum, list):
        kind = shared_json_type(enum)
    declared["type"] = kind if _named(kind, _JSON_TYPES) else "any"
    stated: list[tuple[str, Any]] = []
    items = fragment.get("items")
    if (
        isinstance(items, Mapping)
        and items.keys() == {"type"}
        and _named(items["type"], _JSON_TYPES)
    ):
        stated.append(("items", items["type"]))
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
    """Whether ``value`` is one of ``names``, which a list or mapping never is."""
    return isinstance(value, str) and value in names


def shared_json_type(values: Iterable[Any]) -> str | None:
    """The one JSON type ``values`` share, or ``None`` when they share none (``_json_type``)."""
    kinds = {_json_type(value) for value in values}
    return kinds.pop() if len(kinds) == 1 else None


def field_type(field: serializers.Field) -> tuple[str, str | None]:
    """The JSON type and format of one value ``field`` takes or renders."""
    if isinstance(field, serializers.FileField):
        return "file", None
    for cls, json_type, fmt in _SCALARS:
        if isinstance(field, cls):
            return json_type, fmt
    return "any", None


def input_type(field: serializers.Field) -> tuple[str, str | None]:
    """The JSON type and format of one value ``field`` takes, for the shape check in front of it."""
    json_type, fmt = field_type(field)
    formats = _input_formats(field)
    if formats is not None and any(each != ISO_8601 for each in formats):
        return json_type, None
    if isinstance(field, serializers.DecimalField) and field.localize:
        return "any", None
    return json_type, fmt


def _input_formats(field: serializers.Field) -> Sequence[str] | None:
    """The formats a date or date-time field reads, as DRF reads them when it validates."""
    if isinstance(field, serializers.DateTimeField):
        return getattr(field, "input_formats", api_settings.DATETIME_INPUT_FORMATS)
    if isinstance(field, serializers.DateField):
        return getattr(field, "input_formats", api_settings.DATE_INPUT_FORMATS)
    return None


@dataclasses.dataclass(frozen=True)
class FieldChoices:
    """A choice field's values, their shared JSON type, and their labels."""

    type: str | None
    values: tuple[Any, ...]
    labels: tuple[tuple[Any, Any], ...]


def field_choices(field: serializers.Field) -> FieldChoices | None:
    """The choices ``field`` takes, or ``None`` for a field that is no choice field."""
    if not isinstance(field, serializers.ChoiceField):
        return None
    return _choices_of(field)


def _choices_of(field: serializers.ChoiceField) -> FieldChoices:
    """``field_choices`` for a field known to be a choice field."""
    labels = tuple(field.choices.items())
    values = tuple(value for value, _label in labels)
    if getattr(field, "allow_blank", False) and "" not in values:
        values = (*values, "")
    found = {_json_type(value) for value in values} or {"string"}
    shared = found.pop() if len(found) == 1 else None
    return FieldChoices(type=shared, values=values, labels=labels)


def literal_default(field: serializers.Field) -> Any:
    """``field``'s default as a declaration a transport could print, or the kernel's ``UNSET``."""
    default: Any = field.default
    if default is UNSET or callable(default):
        return UNSET
    return default


def _json_type(value: Any) -> str | None:
    """The JSON type of a scalar value, or ``None`` for anything else."""
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
    """What a list's element declares, as the array's own keywords."""
    if isinstance(field, serializers.MultipleChoiceField):
        own = _choices_of(field)
        if own.type is None:
            return {}
        return {"items": own.type, "choices": own.values, "choice_labels": own.labels}
    child: Any = field.child
    fragment = registered_fragment(registry, child)
    if fragment is not None:
        element = fragment_keywords(fragment, output=False)["type"]
        return {} if element == "any" else {"items": element}
    if isinstance(child, serializers.Serializer):
        return {"items": _rows(child, path, registry)}
    if isinstance(child, serializers.ListField | serializers.ListSerializer):
        return {"items": "array"}
    choices = field_choices(child)
    if choices is not None and choices.type is not None:
        return {
            "items": choices.type,
            "items_nullable": child.allow_null,
            "choices": choices.values,
            "choice_labels": choices.labels,
        }
    json_type, fmt = input_type(child)
    if json_type == "any":
        return {}
    return {
        "items": json_type,
        "items_nullable": child.allow_null,
        "format": fmt if fmt == "decimal" else None,
    }


def _lengths(field: Any) -> dict[str, Any]:
    """A list's ``min_length`` and ``max_length``, with ``allow_empty=False`` a minimum of one."""
    minimum: int | None = getattr(field, "min_length", None)
    if not field.allow_empty:
        minimum = max(minimum or 0, 1)
    return {"min_length": minimum or None, "max_length": getattr(field, "max_length", None)}
