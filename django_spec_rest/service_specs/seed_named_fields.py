"""``seed_named_fields`` - the body fields a ``SerializerValidator`` takes that are no parameter of it."""

from __future__ import annotations

from typing import Any

from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.service_specs.utils import describe_serializer, is_input


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
    fields = describe_serializer(validator.serializer, validator).fields
    writable = {name for name, field in fields.items() if is_input(field)}
    return frozenset(writable.difference(validator.parameters().names()))
