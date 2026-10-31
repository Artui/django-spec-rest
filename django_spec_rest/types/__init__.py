"""Types this adapter owns: the DRF-typed authoring shapes and the view hook chain.

The kernel's own types are imported from ``django_service_specs``, not
re-exported here.
"""

from django_spec_rest.types.field_marking import MARKING
from django_spec_rest.types.http_extras import HttpExtras
from django_spec_rest.types.json_schema_registry import (
    DEFAULT_JSON_SCHEMA_REGISTRY,
    JsonSchemaRegistry,
)
from django_spec_rest.types.offline_context import OfflineContext
from django_spec_rest.types.offline_http_request import OfflineHttpRequest
from django_spec_rest.types.offline_service_view import OfflineServiceView
from django_spec_rest.types.service_view import ServiceView
from django_spec_rest.types.view_hooks import ViewHooks

__all__ = [
    "DEFAULT_JSON_SCHEMA_REGISTRY",
    "MARKING",
    "HttpExtras",
    "JsonSchemaRegistry",
    "OfflineContext",
    "OfflineHttpRequest",
    "OfflineServiceView",
    "ServiceView",
    "ViewHooks",
]
