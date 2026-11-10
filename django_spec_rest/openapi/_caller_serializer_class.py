from __future__ import annotations

import functools
import re
from typing import Any

from drf_spectacular.drainage import set_override
from rest_framework.serializers import Serializer


@functools.cache
def caller_serializer_class(
    serializer: type[Serializer[Any]],
    stem: str,
    *,
    owned: frozenset[str],
    relaxed: frozenset[str],
) -> type[Serializer[Any]]:
    """``serializer`` less its ``owned`` fields, with its ``relaxed`` ones not required."""
    name = _component_name(stem, owned=owned, relaxed=relaxed)
    meta = type(
        "Meta", (serializer.Meta,) if hasattr(serializer, "Meta") else (), {"ref_name": name}
    )

    def get_fields(self: Any) -> dict[str, Any]:
        # The author's ``get_fields``, which ``derived`` overrides from model or dataclass.
        fields = serializer.get_fields(self)
        for field in owned:
            fields.pop(field, None)
        for field in relaxed & fields.keys():
            fields[field].required = False
        return fields

    derived = type(name, (serializer,), {"Meta": meta, "get_fields": get_fields})
    return set_override(derived, "component_name", name)


def _component_name(stem: str, *, owned: frozenset[str], relaxed: frozenset[str]) -> str:
    """The component a body over ``stem`` is named, less ``owned`` and with ``relaxed`` optional."""
    sections = [
        label + "_".join(_spelled(field) for field in sorted(fields))
        for label, fields in (("Less", owned), ("Optional", relaxed))
        if fields
    ]
    name = stem + "__".join(sections)
    return name + "Serializer" if name.endswith("Serializer") else name


def _spelled(field: str) -> str:
    """``field`` as it reads in a component name: ``PascalCase``, or ``0`` and its bytes in hex."""
    if _SNAKE.fullmatch(field):
        return "".join(word.capitalize() for word in field.split("_"))
    return "0" + field.encode().hex()


_SNAKE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z][a-z0-9]*)*")
"""A ``snake_case`` name, letter-led in each word, that a ``PascalCase`` reads back to."""
