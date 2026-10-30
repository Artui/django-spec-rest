"""``JsonSchemaRegistry`` — consumer-extensible type → JSON Schema mappings."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

# A single mapping rule: ``(type, schema_fragment)``.
_Rule = tuple[type, dict[str, Any]]


# The built-in mappings live with the walkers, not here (the filter built-ins
# import django-filter lazily): a registry carries only consumer additions, so
# the empty default stays dependency-free.
@dataclass(frozen=True)
class JsonSchemaRegistry:
    """Consumer-extensible ``type → JSON Schema fragment`` rules for the DRF seats.

    Rules are tried in order and the first match wins, **before** the built-in
    mappings — so a rule both adds support for a custom type and can override a
    built-in. The matched fragment is copied per use, so callers may freely
    mutate the returned schema.

    Immutable: ``extend`` returns a *new* registry rather than mutating, so
    there is no shared global state to leak across callers or tests. Start from
    [`DEFAULT_JSON_SCHEMA_REGISTRY`][django_spec_rest.types.json_schema_registry.DEFAULT_JSON_SCHEMA_REGISTRY],
    the empty base, layer rules on, and hand the result to a seat as its
    ``json_schema_registry=``:

        registry = DEFAULT_JSON_SCHEMA_REGISTRY.extend(
            fields=[(MoneyField, {"type": "string", "format": "money"})],
        )
        validator = SerializerValidator(MySerializer, json_schema_registry=registry)

    That rule describes every ``MoneyField`` of the serializer as the kernel
    spec it serves compiles, where only what the kernel can state is kept: the
    field is a string there and ``format: "money"``, which is none of the
    kernel's four formats, is dropped
    (test_registry_through_the_compiled_spec's
    test_the_kernel_s_schema_states_the_rule_but_for_the_dropped_format). A rule
    ``extend`` prepends wins over the registry's own
    (test_a_rule_an_extension_prepends_wins_over_the_registrys_own).

    Attributes:
        fields: DRF ``Field`` subclasses, matched by ``isinstance`` when a
            ``SerializerValidator`` or ``SerializerPresenter`` walks its
            serializer.
        filters: ``django-filter`` ``Filter`` subclasses, matched by
            ``isinstance``.
        python_types: Bare Python types, matched by *identity*.
    """

    fields: tuple[_Rule, ...] = ()
    filters: tuple[_Rule, ...] = ()
    python_types: tuple[_Rule, ...] = ()

    def extend(
        self,
        *,
        fields: Sequence[_Rule] = (),
        filters: Sequence[_Rule] = (),
        python_types: Sequence[_Rule] = (),
    ) -> JsonSchemaRegistry:
        """Return a new registry with the given rules prepended (they win first)."""
        return replace(
            self,
            fields=tuple(fields) + self.fields,
            filters=tuple(filters) + self.filters,
            python_types=tuple(python_types) + self.python_types,
        )


DEFAULT_JSON_SCHEMA_REGISTRY: JsonSchemaRegistry = JsonSchemaRegistry()
