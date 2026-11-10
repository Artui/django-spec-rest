from __future__ import annotations

from collections.abc import Collection
from typing import Any

from django_spec_rest.openapi.utils import (
    RESERVED_COMPONENTS,
    held_by_package,
    name_taken,
    placed,
)


def reserved_components_hook(
    result: dict[str, Any], generator: Any, request: Any, public: bool, **kwargs: Any
) -> dict[str, Any]:
    """Refuse a ``$ref`` to a component name the package reserves that the package did not write."""
    registry = generator.registry
    written = placed(registry)
    skip = {id(ref) for ref in written}
    reserved = [name for name in RESERVED_COMPONENTS if held_by_package(registry, name)]
    for path, operations in result.get("paths", {}).items():
        for method, operation in operations.items():
            _refuse_foreign(operation, f"The operation {method.upper()} {path}", reserved, skip)
    for components in result.get("components", {}).values():
        for name, schema in components.items():
            _refuse_foreign(schema, f"The component {name!r}", reserved, skip, own=name)
    for name, webhook in result.get("webhooks", {}).items():
        _refuse_foreign(webhook, f"The webhook {name!r}", reserved, skip)
    return result


def _refuse_foreign(
    node: Any, where: str, reserved: Collection[str], skip: set[int], own: str | None = None
) -> None:
    """Raise for a ``$ref`` under ``node`` to a ``reserved`` name, unless its string is in ``skip``."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        for name in reserved:
            if ref == f"#/components/schemas/{name}" and name != own and id(ref) not in skip:
                raise name_taken(where, name)
        children = node.values()
    elif isinstance(node, list):
        children = node
    else:
        return
    for child in children:
        _refuse_foreign(child, where, reserved, skip, own)
