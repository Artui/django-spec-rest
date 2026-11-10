from __future__ import annotations

from dataclasses import is_dataclass
from typing import cast

from rest_framework.serializers import Serializer

from django_spec_rest.service_specs.renderable_serializer_class import renderable_serializer_class


def to_serializer_class(value: type | None) -> type[Serializer] | None:
    """Coerce a seat's serializer declaration to a ``Serializer`` subclass."""
    if value is None:
        return None
    if isinstance(value, type) and issubclass(value, Serializer):
        return value
    if is_dataclass(value):
        return cast("type[Serializer]", renderable_serializer_class(value))
    return None
