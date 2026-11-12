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
    """Refuse a ``$ref`` to a component name the package reserves that the package did not write.

    ``ValidationErrors``, ``PermissionDenied`` and ``NotAuthenticated`` document
    the bodies of a spec's 400, 403 and 401. drf-spectacular keeps the first
    component registered under a name and answers it for every later one, with
    a warning only, so a project's serializer of the same name on a view this
    package does not document (drf-spectacular's own ``AutoSchema``) would be
    documented by the package's body. Where the package registered one of these
    names, every ``$ref`` to it outside the places the package rendered it raises
    ``ImproperlyConfigured``, naming the operation, component or webhook that
    holds it.

    A name the package never registered is a project's to use
    (test_a_project_s_own_reserved_name_is_documented_without_the_package_s).

    Raises:
        ImproperlyConfigured: a reserved name documents something of the
            project's.
    """
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
    """Raise for a ``$ref`` under ``node`` to a ``reserved`` name not in ``skip``."""
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
