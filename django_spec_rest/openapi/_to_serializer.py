"""Convert a seat's serializer declaration into a ``Serializer`` class.

A ``SerializerValidator`` or ``SerializerPresenter`` reads one of three shapes:

- ``None`` — no seat.
- a ``Serializer`` subclass.
- a bare ``@dataclass`` type, auto-wrapped in a ``DataclassSerializer``.

Schema generators only know how to read ``Serializer`` subclasses, so this helper
mirrors the runtime's validation branching to produce a class the generator can
introspect — keeping the schema and the runtime in lockstep."""

from __future__ import annotations

from dataclasses import is_dataclass
from typing import cast

from rest_framework.serializers import Serializer

from django_spec_rest.service_specs.renderable_serializer_class import renderable_serializer_class


def to_serializer_class(value: type | None) -> type[Serializer] | None:
    """Coerce a seat's serializer declaration to a ``Serializer`` subclass.

    Returns ``None`` when ``value`` is ``None`` or an unrecognised shape.
    Bare dataclass types are wrapped in a ``DataclassSerializer`` subclass so
    schema generators see typed properties rather than ``object`` — the same
    class, per dataclass, that the render path serializes through.
    """
    if value is None:
        return None
    if isinstance(value, type) and issubclass(value, Serializer):
        return value
    if is_dataclass(value):
        # A dataclass resolves to a ``DataclassSerializer`` subclass, which is a
        # ``Serializer``; the resolver is annotated for every declaration it
        # passes through, so it cannot say that itself.
        return cast("type[Serializer]", renderable_serializer_class(value))
    return None
