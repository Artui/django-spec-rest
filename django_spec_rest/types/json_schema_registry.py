from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

# A single mapping rule: ``(type, schema_fragment)``.
_Rule = tuple[type, dict[str, Any]]


# Built-in mappings live with the walkers; a registry holds only consumer additions.
@dataclass(frozen=True)
class JsonSchemaRegistry:
    """Consumer-extensible ``type → JSON Schema fragment`` rules for the DRF seats."""

    fields: tuple[_Rule, ...] = ()

    def extend(self, *, fields: Sequence[_Rule] = ()) -> JsonSchemaRegistry:
        """Return a new registry with the given rules prepended (they win first)."""
        return replace(self, fields=tuple(fields) + self.fields)


DEFAULT_JSON_SCHEMA_REGISTRY: JsonSchemaRegistry = JsonSchemaRegistry()
