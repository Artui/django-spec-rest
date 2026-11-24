from __future__ import annotations

from django_service_specs.types.json_schema_registry import JsonSchemaRegistry

DEFAULT_JSON_SCHEMA_REGISTRY: JsonSchemaRegistry = JsonSchemaRegistry()
"""The empty registry: a seat's own rules start here, and the project's stay behind them."""

__all__ = ["DEFAULT_JSON_SCHEMA_REGISTRY", "JsonSchemaRegistry"]
