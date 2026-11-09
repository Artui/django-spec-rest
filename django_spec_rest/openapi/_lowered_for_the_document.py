"""``lowered_for_the_document`` - a kernel schema, written for the document's OpenAPI version."""

from __future__ import annotations

from typing import Any

from drf_spectacular.settings import spectacular_settings

_NULL = "null"


def lowered_for_the_document(schema: dict[str, Any]) -> dict[str, Any]:
    """``schema`` as the document's OpenAPI version reads it: untouched, or lowered from JSON Schema.

    The kernel's schemas are JSON Schema, which OpenAPI 3.1 and later is, so
    ``schema`` itself comes back under them. OpenAPI 3.0, drf-spectacular's
    default ``OAS_VERSION``, is not: ``validate_schema`` refuses the whole
    document over a type list or a ``const``. Under 3.0 the schema is written
    anew, with:

    - ``{"type": [t, "null"]}`` as ``{"type": t, "nullable": true}``;
    - an ``anyOf`` or a ``oneOf`` made only of constants (a labelled choice) as
      an ``enum`` of their values in order, the titles dropped since 3.0 has no
      place for them. A ``{"type": "null"}`` or ``{"const": None}`` member is a
      constant of ``null``: the ``enum`` lists ``None`` and the schema gains
      ``nullable``, because 3.0 needs both to admit it. An empty one, or one
      with any other member, is not an ``enum`` and stays, its members lowered
      in turn. Nor is one beside an ``enum`` the schema already has.

    The walk goes where a schema holds a schema: the values of ``properties``,
    ``items``, ``additionalProperties`` when it is a mapping, and the members
    of ``anyOf``, ``oneOf`` and ``allOf``. It reads no value: ``default``,
    ``enum``, ``const``, ``example`` and ``examples`` are data, and a property
    called ``type`` or ``items`` is a name in ``properties``, never a keyword.
    ``schema`` is not modified, since a kernel schema may be shared.
    """
    if not spectacular_settings.OAS_VERSION.startswith("3.0"):
        return schema
    return _lowered(schema)


def _lowered(schema: dict[str, Any]) -> dict[str, Any]:
    node = dict(schema)
    _nullable(node)
    for keyword in ("anyOf", "oneOf"):
        # One branch to coverage, so the guard's operands are named: a schema
        # already holding an ``enum`` keeps it
        # (test_an_enum_already_there_is_never_replaced).
        if "enum" not in node:
            values = _constants(node.get(keyword))
            if values is not None:
                del node[keyword]
                node["enum"] = values
                if any(value is None for value in values):
                    node["nullable"] = True
    if isinstance(node.get("properties"), dict):
        node["properties"] = {name: _walked(value) for name, value in node["properties"].items()}
    for keyword in ("items", "additionalProperties"):
        if keyword in node:
            node[keyword] = _walked(node[keyword])
    for keyword in ("anyOf", "oneOf", "allOf"):
        if isinstance(node.get(keyword), list):
            node[keyword] = [_walked(member) for member in node[keyword]]
    return node


def _walked(value: Any) -> Any:
    """``value`` lowered where it is a schema; a boolean schema, or a tuple form's list, is as it was."""
    return _lowered(value) if isinstance(value, dict) else value


def _nullable(node: dict[str, Any]) -> None:
    """``node``'s ``[t, "null"]`` type as ``t`` and ``nullable``, in place on the copy ``_lowered`` made."""
    kinds = node.get("type")
    if not isinstance(kinds, list):
        return
    types = [kind for kind in kinds if kind != _NULL]
    # Exactly one type beside one null: ``["string"]`` is not nullable
    # (test_any_other_type_is_as_it_was), nor are two types or none.
    if len(kinds) == 2 and len(types) == 1:
        node["type"] = types[0]
        node["nullable"] = True


def _constants(members: Any) -> list[Any] | None:
    """The values ``members`` are constants of, in order, or ``None`` where any member is more.

    A member is a constant when it is ``{"const": v}`` or the null
    (``{"type": "null"}``), titled or not, and states nothing else: a
    member with a ``description`` or a ``type`` beside its ``const`` would lose
    what it states as an ``enum`` value.
    """
    if not isinstance(members, list) or not members:
        return None
    values: list[Any] = []
    for member in members:
        if not isinstance(member, dict):
            return None
        stated = set(member) - {"title"}
        if stated == {"const"}:
            values.append(member["const"])
        elif stated == {"type"} and member["type"] == _NULL:
            values.append(None)
        else:
            return None
    return values
