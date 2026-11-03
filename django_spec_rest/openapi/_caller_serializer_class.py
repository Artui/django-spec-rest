"""The serializer a ``SerializerValidator`` body is documented by where ``input_data`` reaches it.

The author's serializer lists every field the Validator takes, while a caller
is asked only for what the server does not fill: a field ``input_data`` is
annotated to fill is never the caller's, and one it may fill is not required
of the caller. OPTIONS reads that off the kernel's ``spec_caller_input_schema``;
drf-spectacular reads a serializer, so the body is documented by a subclass of
the author's that drops the one and relaxes the other, under a component name
of its own.
"""

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
    """``serializer`` less its ``owned`` fields, with its ``relaxed`` ones not required.

    ``stem`` is the component name drf-spectacular gives ``serializer`` itself,
    and the subclass is named from it by ``component_name``. The name is set
    both as ``Meta.ref_name`` and as the ``component_name`` override, since an
    ``@extend_schema_serializer(component_name=...)`` on the author's class is
    inherited and outranks ``Meta.ref_name``
    (test_a_base_s_component_name_is_the_stem_and_not_the_name). Without a
    name of its own, a plain serializer's component collides with the base's,
    which drf-spectacular warns of and resolves to the first one documented
    (test_no_two_components_share_a_name), and a ``DataclassSerializer``'s,
    which it identifies by its dataclass, reuses the base's without a word
    (test_a_dataclass_gets_a_component_of_its_own). ``Meta`` subclasses the
    author's, so a ``ModelSerializer`` keeps its model and a
    ``DataclassSerializer`` its dataclass.

    Cached per key, so one schema's every operation over the same body shares
    one class, and so one component: drf-spectacular tells two classes under
    one name apart, and warns. The cost is a strong reference to each class,
    bounded by the declared specs, as ``renderable_serializer_class`` holds its
    dataclasses.
    """
    name = _component_name(stem, owned=owned, relaxed=relaxed)
    meta = type(
        "Meta", (serializer.Meta,) if hasattr(serializer, "Meta") else (), {"ref_name": name}
    )

    def get_fields(self: Any) -> dict[str, Any]:
        # The author's own ``get_fields``, which ``derived`` overrides: a
        # ``ModelSerializer``'s builds its fields from the model, a
        # ``DataclassSerializer``'s from the dataclass.
        fields = serializer.get_fields(self)
        for field in owned:
            fields.pop(field, None)
        for field in relaxed & fields.keys():
            fields[field].required = False
        return fields

    derived = type(name, (serializer,), {"Meta": meta, "get_fields": get_fields})
    return set_override(derived, "component_name", name)


def _component_name(stem: str, *, owned: frozenset[str], relaxed: frozenset[str]) -> str:
    """The component a body over ``stem`` is named, less ``owned`` and with ``relaxed`` optional.

    ``Less`` and the fields dropped, then ``Optional`` and the fields relaxed,
    each set in sorted order with its fields joined by ``_``, and the two
    sections, where both are present, by ``__``: ``TaskLessOwner``,
    ``TaskOptionalOwner``, ``TaskLessOwner_Tenant__OptionalNote``. A
    lower ``snake_case`` field is spelled in ``PascalCase``, ``owner_id`` as
    ``OwnerId``; any other name is spelled ``0`` and its UTF-8 bytes in hex,
    so no spelling holds an ``_`` and every one reads back to its field.
    That is what keeps two different key sets over one stem apart: ``{a_b,
    c}`` and ``{a, b_c}`` would both read ``ABC`` concatenated
    (test_fields_are_joined_so_no_two_sets_share_a_name), and a field named
    ``a_optional_b`` would read as ``a`` and an optional ``b``
    (test_the_two_sections_cannot_be_read_as_one).

    A name ending ``Serializer`` gets that suffix twice, since drf-spectacular
    takes one off every component name
    (test_a_name_ending_serializer_keeps_it). The ``Patched`` of a partial
    body and the ``Request`` of ``COMPONENT_SPLIT_REQUEST`` are
    drf-spectacular's to add, as it adds them to the author's own component.
    """
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
"""A lower ``snake_case`` name, each word starting with a letter: one ``PascalCase`` reads back to."""
