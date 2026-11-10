from __future__ import annotations

import dataclasses
import operator
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.datastructures import MultiValueDict
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.validation.validated import Validated
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from rest_framework import serializers
from rest_framework.fields import get_error_detail
from rest_framework_dataclasses.serializers import DataclassSerializer

from django_spec_rest.service_specs.drf_invalid_arguments import DRFInvalidArguments
from django_spec_rest.service_specs.utils import (
    author_keys,
    bind_serializer,
    bound_instance,
    describe_serializer,
    input_parameters,
    input_view_layers,
    provider_owned,
    serializer_context,
    server_values,
    validator_input,
)
from django_spec_rest.types.json_schema_registry import JsonSchemaRegistry

# What this Validator binds into the call's pool: the bound serializer. A field
# of that name is the serializer's alone, never a parameter, and a validated key
# of that name is handed on in ``data`` alone.
BOUND: frozenset[str] = frozenset({"serializer"})


class SerializerValidator(Validator):
    """A Validator whose declaration is a DRF serializer, or a dataclass read through one."""

    def __init__(
        self,
        serializer: type[Any],
        *,
        serializer_context: Callable[..., Mapping[str, Any]] | None = None,
        lenient: bool = False,
        excluded: frozenset[str] = frozenset(),
        server_owned: frozenset[str] = frozenset(),
        json_schema_registry: JsonSchemaRegistry | None = None,
    ) -> None:
        # One branch to coverage, so each condition is held by its own test: the ``type`` by test_anything_but_a_serializer_class_or_a_dataclass_is_refused_when_declared[an-instance], which ``issubclass`` would raise on; the serializer class by test_parameters_are_the_walked_fields, and the dataclass by test_a_dataclass_s_data_is_its_instance_and_its_values_its_fields, each of which is refused without its own; and [another-class] holds that the two are the only declarations taken.
        if not (
            isinstance(serializer, type)
            and (
                issubclass(serializer, serializers.Serializer)
                or dataclasses.is_dataclass(serializer)
            )
        ):
            raise ImproperlyConfigured(
                f"SerializerValidator takes a Serializer subclass or a dataclass; got {serializer!r}."
            )
        self.serializer = serializer
        self.serializer_context = serializer_context
        self.lenient = lenient
        self.excluded = excluded
        self.server_owned = server_owned
        self.json_schema_registry = json_schema_registry
        self.supports_partial = not (
            dataclasses.is_dataclass(serializer) or issubclass(serializer, DataclassSerializer)
        )

    def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
        """The serializer's input fields, as Parameters."""
        seeded = self._seeded()
        walked = Parameters.of(
            *(param for param in self._walk(call_context) if param.name not in seeded)
        )
        if not self.lenient:
            return walked
        return Parameters.of(
            *(Parameter(param.name, "any", required=False, nullable=True) for param in walked)
        )

    @property
    def unsendable(self) -> frozenset[str]:
        """The required input fields no call on the kernel route can send."""
        seeded = self._seeded()
        return frozenset(
            param.name for param in self._walk() if param.required and param.name in seeded
        )

    def _seeded(self) -> frozenset[str]:
        """The field names this Validator leaves out of ``parameters()``: the one place that list is written."""
        return RESERVED_POOL_SEEDS | BOUND | self.excluded

    def _walk(self, call_context: dict[str, Any] | None = None) -> Parameters:
        """Every input field of the described serializer as a Parameter, seed-named ones included."""
        return input_parameters(
            describe_serializer(self.serializer, self, call_context=call_context),
            registry=self.json_schema_registry,
        )

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        """The validated values, keyed by source, or ``DRFInvalidArguments`` carrying DRF's detail."""
        return self._validated(arguments, context).values

    def validated(self, arguments: Mapping[str, Any], context: ValidationContext) -> Validated:
        """The values, ``validated_data`` as the call's ``data``, and the bound ``serializer``."""
        return self._validated(arguments, context)

    def validated_many(
        self,
        rows: Mapping[int, Mapping[str, Any]],
        context: ValidationContext,
        *,
        many_argument: str,
    ) -> Validated:
        """The rows validated once as DRF's list serializer, the one serializer bound for the call."""
        self._refuse_partial(context)
        indices = list(rows)
        serializer = self._serializer(
            context, data=list(rows.values()), many=True, partial=context.partial
        )
        if not serializer.is_valid():
            raise DRFInvalidArguments(_by_row(serializer.errors, indices))
        data: list[Any] = _cleared(serializer, list(serializer.validated_data))
        return Validated(
            values={many_argument: [_values(row) for row in data]},
            data=data,
            pool={"serializer": serializer},
        )

    def _validated(self, arguments: Mapping[str, Any], context: ValidationContext) -> Validated:
        # Neither public method calls the other, so a subclass may extend either through the other without the two calling each other forever.
        self._refuse_partial(context)
        serializer = self._bind(arguments, context)
        if not serializer.is_valid():
            raise DRFInvalidArguments(serializer.errors)
        data: Any = serializer.validated_data
        held = _server_values(serializer, server_values(self, context.principal))
        _lay_back(data, serializer, held)
        if not isinstance(serializer.initial_data, MultiValueDict):
            data = _cleared(serializer, data)
            held = {name: _cleared(serializer.fields[name], value) for name, value in held.items()}
        values = _values(data)
        handed = _handed(serializer, held, author_keys(self, context.principal))
        values.update(handed)
        values = _unseeded(values, context)
        return Validated(
            values=self._unowned(serializer, values, handed.keys(), context.principal),
            data=data,
            pool={"serializer": serializer},
        )

    def _unowned(
        self,
        serializer: serializers.Serializer,
        values: dict[str, Any],
        kept: Iterable[str],
        principal: Any,
    ) -> dict[str, Any]:
        """``values`` less each ``server_owned`` key the client's input became."""
        owned = self.server_owned | provider_owned(self, principal)
        owned = owned.union(*(_sources(serializer, name) for name in owned)).difference(kept)
        return {name: value for name, value in values.items() if name not in owned}

    def _refuse_partial(self, context: ValidationContext) -> None:
        # One branch to coverage: test_a_partial_call_over_a_dataclass_is_refused holds both together, and each alone is held by a call it must not refuse: test_a_partial_call_takes_a_required_field_left_out_and_returns_what_was_sent (a partial serializer) and test_a_dataclass_s_data_is_its_instance_and_its_values_its_fields (a whole dataclass call).
        if context.partial and not self.supports_partial:
            raise ImproperlyConfigured(
                f"SerializerValidator({self.serializer.__qualname__}) cannot validate a partial "
                "call: a DataclassSerializer builds its instance from every field. Declare the "
                "input as a Serializer subclass to take a partial call."
            )

    def _bind(
        self, arguments: Mapping[str, Any], context: ValidationContext
    ) -> serializers.Serializer:
        """The serializer, bound to the call's input: the edge's body for it, else ``arguments``."""
        return self._serializer(
            context,
            data=validator_input(self, arguments, context.principal),
            instance=bound_instance(context.target),
            partial=context.partial,
        )

    def _serializer(self, context: ValidationContext, **kwargs: Any) -> serializers.Serializer:
        """The serializer bound as ``kwargs`` binds it, under the call's context."""
        return bind_serializer(
            self.serializer, context=self._context(context, kwargs["data"]), **kwargs
        )

    def _context(
        self, context: ValidationContext, arguments: Mapping[str, Any] | list[Any]
    ) -> dict[str, Any]:
        """The serializer context for this call: DRF's, the view's input hooks, then the spec's."""
        return serializer_context(
            context.principal,
            context.ambient,
            arguments,
            view_layers=input_view_layers(self, context.principal),
            provider=self.serializer_context,
            call_context=context.call_context,
        )


def _server_values(serializer: serializers.Serializer, put: Mapping[str, Any]) -> dict[str, Any]:
    """The server's value for each field of ``put``, validated as DRF's field loop validates one, on its own."""
    fields = serializer.fields
    held: dict[str, Any] = {}
    errors: dict[str, Any] = {}
    for name, field in fields.items():
        if name not in put or field.read_only:
            continue
        method = getattr(serializer, f"validate_{name}", None)
        try:
            value = field.run_validation(_server_primitive(field, put[name]))
            if method is not None:
                value = method(value)
        except serializers.ValidationError as exc:
            errors[name] = exc.detail
        except DjangoValidationError as exc:
            errors[name] = get_error_detail(exc)
        except serializers.SkipField:
            pass
        else:
            held[name] = value
    if errors:
        raise DRFInvalidArguments(errors)
    return held


def _server_primitive(field: serializers.Field, value: Any) -> Any:
    """The server's ``value`` as ``field`` takes it: as put, unless the field takes no input."""
    if isinstance(field, serializers.HiddenField):
        return serializers.empty
    return value


def _handed(
    serializer: serializers.Serializer, held: Mapping[str, Any], authored: Mapping[str, str]
) -> dict[str, Any]:
    """Each value of ``held``, by the names its field's value is handed to a parameter under."""
    handed: dict[str, Any] = {}
    for name, value in held.items():
        source = serializer.fields[name].source_attrs
        key = source[0] if len(source) == 1 else name
        handed[key] = value
        handed[authored.get(name, key)] = value
    return handed


def _sources(serializer: serializers.Serializer, name: str) -> tuple[str, ...]:
    """The key ``validated_data`` holds the value of the field named ``name`` under, if any."""
    field = serializer.fields.get(name)
    attrs = field.source_attrs if field is not None else []
    return tuple(attrs[:1])


def _lay_back(data: Any, serializer: serializers.Serializer, held: Mapping[str, Any]) -> None:
    """Each of ``held`` written back over its field's ``source`` key in ``data``, where it still is."""
    for name, value in held.items():
        *path, last = serializer.fields[name].source_attrs or [None]
        target: Any = data
        for key in path:
            target = target.get(key) if isinstance(target, Mapping) else None
        if isinstance(target, MutableMapping) and last in target:
            target[last] = value


def _cleared(field: serializers.Field | None, value: Any) -> Any:
    """``value`` as ``field`` validated it, each file field's ``None`` the empty file ``""``."""
    if isinstance(field, serializers.FileField):
        return "" if value is None else value
    if isinstance(field, serializers.ListSerializer):
        if not isinstance(value, list):
            return value
        rows = [_cleared(field.child, row) for row in value]
        return value if all(map(operator.is_, rows, value)) else rows
    if isinstance(field, serializers.Serializer):
        for child in field.fields.values():
            attrs = child.source_attrs
            value = _cleared_at(value, attrs, child) if attrs else _cleared(child, value)
    return value


def _cleared_at(value: Any, attrs: list[str], field: serializers.Field) -> Any:
    """``value`` with what ``field`` validated at ``attrs`` cleared, or itself if nothing changed."""
    if not isinstance(value, Mapping) or attrs[0] not in value:
        return value
    head, *rest = attrs
    held = value[head]
    cleared = _cleared_at(held, rest, field) if rest else _cleared(field, held)
    return value if cleared is held else {**value, head: cleared}


def _by_row(errors: Any, indices: list[int]) -> dict[Any, Any]:
    """A list serializer's errors, each failing row keyed by the caller's own index."""
    if isinstance(errors, list):
        errors = {position: row for position, row in enumerate(errors) if row}
    return {indices[key] if isinstance(key, int) else key: detail for key, detail in errors.items()}


def _unseeded(values: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
    """``values`` less every key a seed of the call, or the bound serializer, holds."""
    seeded = RESERVED_POOL_SEEDS | context.ambient.keys() | BOUND
    return {name: value for name, value in values.items() if name not in seeded}


def _values(data: Any) -> dict[str, Any]:
    """The values a call's ``validated_data`` spreads by name."""
    if isinstance(data, Mapping):
        return dict(data)
    if dataclasses.is_dataclass(data):
        return {f.name: getattr(data, f.name) for f in dataclasses.fields(data) if f.init}
    return {}
