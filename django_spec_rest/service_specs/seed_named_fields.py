from __future__ import annotations

from typing import Any

from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.service_specs.utils import describe_serializer, is_input


def seed_named_fields(
    validator: Any, *, call_context: dict[str, Any] | None = None
) -> frozenset[str]:
    """The writable fields of ``validator``'s serializer that are no parameter of it."""
    if not isinstance(validator, SerializerValidator):
        return frozenset()
    fields = describe_serializer(validator.serializer, validator, call_context=call_context).fields
    writable = {name for name, field in fields.items() if is_input(field)}
    return frozenset(writable.difference(validator.parameters(call_context=call_context).names()))
