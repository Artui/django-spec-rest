from __future__ import annotations

import dataclasses
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from types import MappingProxyType
from typing import Any, Final

from django.core.exceptions import ImproperlyConfigured
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output, OutputField
from django_service_specs.output.presentation_context import PresentationContext
from django_service_specs.output.presenter import Presenter
from django_service_specs.parameters.invalid_arguments import (
    InvalidArguments as KernelInvalidArguments,
)
from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS
from rest_framework import serializers
from rest_framework.fields import empty as _drf_empty

from django_spec_rest.service_specs.base_serializer_context import base_serializer_context
from django_spec_rest.service_specs.drf_invalid_arguments import DRFInvalidArguments
from django_spec_rest.service_specs.renderable_serializer_class import (
    renderable_serializer_class,
)
from django_spec_rest.service_specs.utils import (
    MAX_SERIALIZER_APPEARANCES,
    fragment_keywords,
    output_view_layers,
    registered_fragment,
    serializer_context,
    shared_json_type,
)
from django_spec_rest.types.field_marking import MARKING
from django_spec_rest.types.json_schema_registry import JsonSchemaRegistry

# The kernel's JSON type and format per DRF field class, first ``isinstance``
# hit wins, so a subclass precedes its base. A format the kernel does not name
# (``time``, ``uuid``, ``email``, ``uri``) is left out: those fields still
# render a string, and a format a kernel reader cannot act on
# is left off rather than refused.
_SCALARS: Final[tuple[tuple[type[serializers.Field], str, str | None], ...]] = (
    (serializers.BooleanField, "boolean", None),
    (serializers.IntegerField, "integer", None),
    (serializers.FloatField, "number", None),
    (serializers.DecimalField, "string", "decimal"),
    (serializers.DateTimeField, "string", "date-time"),
    (serializers.DateField, "string", "date"),
    (serializers.TimeField, "string", None),
    (serializers.DurationField, "string", None),
    (serializers.UUIDField, "string", None),
    (serializers.CharField, "string", None),
    (serializers.DictField, "object", None),
)


@dataclasses.dataclass(frozen=True)
class _Shape:
    """What one DRF field declares, before it is named: the half ``OutputField`` shares."""

    type: str | None
    format: str | None = None
    fields: Output | None = None
    items: str | Output | None = None
    items_nullable: bool = False
    choices: tuple[tuple[Any, str], ...] | None = None


class SerializerPresenter(Presenter):
    """An operation's output declared as a DRF serializer, rendered through it."""

    def __init__(
        self,
        serializer_class: type,
        *,
        field_audiences: Mapping[str, FieldMarking] | None = None,
        serializer_context: Callable[..., Mapping[str, Any]] | None = None,
        value_keyword: str | None = "result",
        shaped: bool = False,
        json_schema_registry: JsonSchemaRegistry | None = None,
    ) -> None:
        # Resolved, not instantiated: specs load at import, and fields need the app registry.
        if not isinstance(serializer_class, type):
            raise ImproperlyConfigured(_REFUSED.format(declared=serializer_class))
        resolved = renderable_serializer_class(serializer_class)
        if not issubclass(resolved, serializers.BaseSerializer):
            raise ImproperlyConfigured(_REFUSED.format(declared=serializer_class))
        for name, marking in (field_audiences or {}).items():
            if not isinstance(marking, FieldMarking):
                raise ImproperlyConfigured(
                    f"SerializerPresenter: field_audiences[{name!r}] is {marking!r}, not a "
                    "FieldMarking. Use FieldMarking.handle() / .hidden() / .label()."
                )
        self.serializer_class = resolved
        self.field_audiences: Mapping[str, FieldMarking] = MappingProxyType(
            dict(field_audiences or {})
        )
        self.serializer_context = serializer_context
        self.value_keyword = value_keyword
        self.shaped = shaped
        self.json_schema_registry = json_schema_registry

    def output(self) -> Output:
        """The serializer's fields as an Output, with ``field_audiences`` layered on."""
        serializer = self.serializer_class(context=_context())
        output = (
            _output(serializer, path=(), registry=self.json_schema_registry)
            if isinstance(serializer, serializers.Serializer)
            else Output()
        )
        if self.shaped:
            output = _none_always_present(output)
        unknown = sorted(set(self.field_audiences) - set(output.names()))
        if unknown:
            raise ImproperlyConfigured(
                f"{self.serializer_class.__name__}: field_audiences names {unknown!r}, which "
                f"the serializer does not output. It outputs {list(output.names())!r}."
            )
        return Output(
            tuple(
                dataclasses.replace(field, marking=self.field_audiences[field.name])
                if field.name in self.field_audiences
                else field
                for field in output
            )
        )

    def present(self, value: Any) -> Any:
        """One value as the serializer's ``.data``, with no call to render for."""
        return self.presented(value, None)

    def presented(self, value: Any, context: PresentationContext | None) -> Any:
        """One value as the serializer's ``.data``, under the context of the call it belongs to."""
        if value is None:
            return None
        with _refusals_as_the_kernel_s():
            return self.serializer_class(
                value, context=self._context(value, context, extras=self._named(value))
            ).data

    def presented_rows(
        self, values: Sequence[Any], context: PresentationContext | None
    ) -> list[Any]:
        """A list's rows as one ``many=True`` render, its context asked for once."""
        rows = [value for value in values if value is not None]
        with _refusals_as_the_kernel_s():
            rendered = list(
                self.serializer_class(
                    rows,
                    many=True,
                    context=self._context(
                        rows, context, extras={**self._named(rows), "page": rows}
                    ),
                ).data
            )
        if len(rows) == len(values):
            return rendered
        if len(rendered) != len(rows):
            raise ImproperlyConfigured(
                f"{self.serializer_class.__name__}: its list serializer answered {len(rendered)} "
                f"rows for {len(rows)} rows. Answer one row per value, in the order given."
            )
        answers = iter(rendered)
        return [None if value is None else next(answers) for value in values]

    def _named(self, value: Any) -> dict[str, Any]:
        """``value`` under ``value_keyword``, or nothing where the presenter names none."""
        return {} if self.value_keyword is None else {self.value_keyword: value}

    def _context(
        self, value: Any, context: PresentationContext | None, *, extras: Mapping[str, Any]
    ) -> dict[str, Any]:
        """The serializer context for ``value``, one row or a list's rows, in ``context``'s call."""
        if context is None:
            return _context()
        return serializer_context(
            context.principal,
            context.ambient,
            None,
            view_layers=output_view_layers(
                context.ambient, value if self.value_keyword is not None else None
            ),
            provider=self.serializer_context,
            extras=extras,
            call_context=context.call_context,
            shapes=context.shapes,
        )


_REFUSED: Final = (
    "SerializerPresenter takes a serializer class or a dataclass type; got {declared!r}."
)


@contextmanager
def _refusals_as_the_kernel_s() -> Generator[None]:
    """A serializer's ``ValidationError`` raised as the dual ``DRFInvalidArguments``."""
    try:
        yield
    except KernelInvalidArguments:
        raise
    except serializers.ValidationError as exc:
        detail = exc.detail
        raise DRFInvalidArguments(
            detail if isinstance(detail, Mapping) else {NON_FIELD_ERRORS: detail}
        ) from exc


def _context() -> dict[str, Any]:
    """The description context: DRF's three keys, each ``None``, for no call."""
    return base_serializer_context(view=None, request=None)


def _output(
    serializer: serializers.Serializer,
    *,
    path: tuple[type, ...],
    registry: JsonSchemaRegistry | None = None,
) -> Output:
    path = (*path, type(serializer))
    return Output(
        tuple(
            _output_field(name, field, serializer=serializer, path=path, registry=registry)
            for name, field in serializer.fields.items()
            if not field.write_only
        )
    )


def _output_field(
    name: str,
    field: serializers.Field,
    *,
    serializer: serializers.Serializer,
    path: tuple[type, ...],
    registry: JsonSchemaRegistry | None = None,
) -> OutputField:
    """One rendered field as an ``OutputField``."""
    fragment = registered_fragment(registry, field)
    if fragment is not None:
        declared = fragment_keywords(fragment, output=True)
        declared.update(
            nullable=field.allow_null or declared.get("nullable", False),
            label=_declared_label(name, field) or declared.get("label"),
            always_present=_always_rendered(field),
            marking=_marking(field, serializer=serializer, name=name),
        )
        return OutputField(name, declared.pop("type"), **declared)
    shape = _shape(field, path=path, registry=registry)
    return OutputField(
        name,
        shape.type or "any",
        format=shape.format,
        nullable=field.allow_null,
        label=_declared_label(name, field),
        choices=shape.choices,
        always_present=_always_rendered(field),
        marking=_marking(field, serializer=serializer, name=name),
        fields=shape.fields,
        items=shape.items,
        items_nullable=shape.items_nullable,
    )


def _none_always_present(output: Output) -> Output:
    """``output`` with no field at any depth ``always_present``: a shaped spec's output."""
    return Output(
        tuple(
            dataclasses.replace(
                field,
                always_present=False,
                fields=None if field.fields is None else _none_always_present(field.fields),
                items=(
                    _none_always_present(field.items)
                    if isinstance(field.items, Output)
                    else field.items
                ),
            )
            for field in output
        )
    )


def _shape(
    field: serializers.Field, *, path: tuple[type, ...], registry: JsonSchemaRegistry | None = None
) -> _Shape:
    """One field's type, and what it nests, with ``type=None`` where DRF names none."""
    if isinstance(field, serializers.ListSerializer | serializers.ListField):
        child: Any = field.child
        fragment = (
            registered_fragment(registry, child)
            if isinstance(field, serializers.ListField)
            else None
        )
        if fragment is not None:
            kind = fragment_keywords(fragment, output=True)["type"]
            return _Shape("array", items=None if kind == "any" else kind)
        element = _shape(child, path=path, registry=registry)
        items = element.fields if element.fields is not None else element.type
        return _Shape("array", items=items, items_nullable=items is not None and child.allow_null)
    if isinstance(field, serializers.ManyRelatedField):
        return _Shape("array")
    if isinstance(field, serializers.Serializer):
        if path.count(type(field)) >= MAX_SERIALIZER_APPEARANCES:
            return _Shape("object")
        return _Shape("object", fields=_output(field, path=path, registry=registry))
    if isinstance(field, serializers.MultipleChoiceField):
        choices = _choices(field)
        return _Shape("array", items=_choices_type(choices), choices=choices)
    if isinstance(field, serializers.ChoiceField):
        choices = _choices(field)
        json_type = _choices_type(choices)
        return _Shape(json_type, choices=choices if json_type else None)
    for cls, json_type, fmt in _SCALARS:
        if isinstance(field, cls):
            return _Shape(json_type, format=fmt)
    return _Shape(None)


def _choices(field: serializers.ChoiceField) -> tuple[tuple[Any, str], ...]:
    # ``str()`` for a lazy translation, read in the language active when the output is read.
    return tuple((value, str(display)) for value, display in field.choices.items())


def _choices_type(choices: tuple[tuple[Any, str], ...]) -> str | None:
    """The JSON type every non-null choice value shares, or ``None`` when they share none."""
    return shared_json_type(value for value, _ in choices if value is not None)


def _declared_label(name: str, field: serializers.Field) -> str | None:
    """The field's ``label`` when its author wrote one, else ``None``."""
    label = str(field.label)
    return None if label == name.replace("_", " ").capitalize() else label


def _always_rendered(field: serializers.Field) -> bool:
    """Whether DRF is bound to emit this field's key."""
    return bool(field.required or field.default is not _drf_empty or field.allow_null)


def _marking(
    field: serializers.Field, *, serializer: serializers.Serializer, name: str
) -> FieldMarking | None:
    """The field's ``FieldMarking``, or ``None``."""
    style: dict[Any, Any] = field.style or {}
    if MARKING in style and not isinstance(style[MARKING], FieldMarking):
        raise ImproperlyConfigured(
            f"{type(serializer).__name__}.{name}: style[{MARKING!r}] is {style[MARKING]!r}, "
            "not a FieldMarking. Use FieldMarking.handle() / .hidden() / .label(); a bare "
            "value here is silently ignored."
        )
    return next((value for value in style.values() if isinstance(value, FieldMarking)), None)
