from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, TypeVar

from drf_spectacular.drainage import warn
from drf_spectacular.plumbing import append_meta
from rest_framework import serializers

from django_spec_rest.openapi._lowered_for_the_document import lowered_for_the_document
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.service_specs.utils import registered_fragment
from django_spec_rest.types.json_schema_registry import JsonSchemaRegistry

_MARK = "_spec_rest_field_rules"
_UNRESOLVABLE = ("$ref", "$defs", "definitions")

_Serializer = TypeVar("_Serializer", bound=serializers.BaseSerializer)


@dataclass(frozen=True)
class FieldRules:
    """The schema rules a documented serializer's fields are typed by, as its seat's are.

    Carried on the root serializer: spectacular maps it after the seat is gone."""

    registry: JsonSchemaRegistry | None = None
    project_registry: bool = True

    @classmethod
    def of_seat(cls, seat: SerializerValidator | SerializerPresenter) -> FieldRules:
        """The rules ``seat`` declares its fields by."""
        return cls(seat.json_schema_registry, seat.project_registry)

    @classmethod
    def for_field(cls, field: serializers.Field) -> FieldRules:
        """The rules carried by ``field``'s root serializer, or the project's alone."""
        return getattr(field.root, _MARK, None) or cls()

    def on(self, serializer: _Serializer) -> _Serializer:
        """``serializer``, carrying these rules for every field the document maps under it."""
        setattr(serializer, _MARK, self)
        return serializer

    def schema(self, field: serializers.Field) -> dict[str, Any] | None:
        """``field``'s rule as the document states it, or ``None`` where no rule types it."""
        fragment = registered_fragment(field, self.registry, project_registry=self.project_registry)
        if fragment is None:
            return None
        return lowered_for_the_document(_resolvable(copy.deepcopy(fragment), field))

    @staticmethod
    def beside(schema: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
        """``schema`` with ``meta``, a type list's null stated once (the nullable tests)."""
        meta = dict(meta)
        kinds = schema.get("type")
        if isinstance(kinds, list) and meta.pop("nullable", False) and "null" not in kinds:
            schema["type"] = [*kinds, "null"]
        return append_meta(schema, meta)


def _resolvable(node: Any, field: serializers.Field) -> Any:
    """``node`` without the references the document has no target for, each one named."""
    if isinstance(node, list):
        return [_resolvable(member, field) for member in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        warn(
            f"{type(field).__name__}'s schema rule names {node['$ref']!r}, which the OpenAPI "
            f"document has no component for, so {field.field_name!r} is documented without it."
        )
    kept = {key: value for key, value in node.items() if key not in _UNRESOLVABLE}
    for key, value in kept.items():
        if key == "properties" and isinstance(value, dict):
            kept[key] = {name: _resolvable(each, field) for name, each in value.items()}
        else:
            kept[key] = _resolvable(value, field)
    return kept
