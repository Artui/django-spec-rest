from __future__ import annotations

from typing import Any

from django_service_specs.affordances.utils import (
    AFFORDANCES_KEY,
    affordance_schema,
    rendered_affordances,
)
from django_service_specs.registry.spec_registry import SpecRegistry
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.spec_link import SpecLink

from django_spec_rest.views.linked_affordances import LINK_METHODS


def documented_affordances(
    spec: SelectorSpec, routes: SpecRegistry | None
) -> dict[str, Any] | None:
    """The ``affordances`` object a row of ``spec`` carries; ``href`` and ``method`` where named."""
    affordances = rendered_affordances(kernel_spec(spec))
    if affordances is None:
        return None
    schema = affordance_schema(affordances)
    for name, declared in affordances.items():
        target = declared.spec if isinstance(declared, SpecLink) else declared
        if routes is None or not isinstance(target, ServiceSpec) or routes.name_of(target) is None:
            continue
        entry = schema["properties"][name]
        entry["properties"] = {
            **entry["properties"],
            "href": {"type": "string", "format": "uri"},
            "method": {"type": "string", "enum": [method.upper() for method in LINK_METHODS]},
        }
    return {
        "type": "object",
        "properties": {AFFORDANCES_KEY: schema},
        "required": [AFFORDANCES_KEY],
    }
