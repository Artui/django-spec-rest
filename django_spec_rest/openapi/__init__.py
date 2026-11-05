"""Opt-in OpenAPI / Swagger integration for ``django-spec-rest``.

The framework-agnostic helpers live here:
[`enable_openapi`][django_spec_rest.openapi.enable_openapi.enable_openapi], and
the schema-only serializers documenting the bodies a service's refusals are
answered with, which a project declares with
``@extend_schema(responses=...)``:
[`ServiceErrorSerializer`][django_spec_rest.openapi.service_error_serializer.ServiceErrorSerializer],
[`ServiceValidationErrorSerializer`][django_spec_rest.openapi.service_validation_error_serializer.ServiceValidationErrorSerializer],
[`ServiceNotFoundSerializer`][django_spec_rest.openapi.service_not_found_serializer.ServiceNotFoundSerializer],
[`ServiceConflictSerializer`][django_spec_rest.openapi.service_conflict_serializer.ServiceConflictSerializer],
[`ActionUnavailableSerializer`][django_spec_rest.openapi.action_unavailable_serializer.ActionUnavailableSerializer],
[`PermissionDeniedSerializer`][django_spec_rest.openapi.permission_denied_serializer.PermissionDeniedSerializer]
and
[`NotAuthenticatedSerializer`][django_spec_rest.openapi.not_authenticated_serializer.NotAuthenticatedSerializer];
and the spec ``metadata`` key
[`SERVICE_ERROR_METADATA_KEY`][django_spec_rest.openapi.service_error_metadata_key.SERVICE_ERROR_METADATA_KEY]
by which a spec declares the ``422`` of a plain ``ServiceError``. Importing this module is safe even without ``drf-spectacular`` installed; it does
not pull in the schema-generator code itself.

The actual ``drf-spectacular`` integration lives in
``django_spec_rest.openapi.service_auto_schema``. That module
imports ``drf-spectacular`` at the top and is loaded only via
[`enable_openapi`][django_spec_rest.openapi.enable_openapi.enable_openapi].

Install the optional dependency with:

    pip install django-spec-rest[spectacular]

Then call
[`enable_openapi`][django_spec_rest.openapi.enable_openapi.enable_openapi] once
from ``AppConfig.ready()``."""

from django_spec_rest.openapi.action_unavailable_serializer import (
    ActionUnavailableSerializer,
)
from django_spec_rest.openapi.enable_openapi import enable_openapi
from django_spec_rest.openapi.not_authenticated_serializer import (
    NotAuthenticatedSerializer,
)
from django_spec_rest.openapi.permission_denied_serializer import (
    PermissionDeniedSerializer,
)
from django_spec_rest.openapi.service_conflict_serializer import (
    ServiceConflictSerializer,
)
from django_spec_rest.openapi.service_error_metadata_key import (
    SERVICE_ERROR_METADATA_KEY,
)
from django_spec_rest.openapi.service_error_serializer import (
    ServiceErrorSerializer,
)
from django_spec_rest.openapi.service_not_found_serializer import (
    ServiceNotFoundSerializer,
)
from django_spec_rest.openapi.service_validation_error_serializer import (
    ServiceValidationErrorSerializer,
)

__all__ = [
    "SERVICE_ERROR_METADATA_KEY",
    "ActionUnavailableSerializer",
    "NotAuthenticatedSerializer",
    "PermissionDeniedSerializer",
    "ServiceConflictSerializer",
    "ServiceErrorSerializer",
    "ServiceNotFoundSerializer",
    "ServiceValidationErrorSerializer",
    "enable_openapi",
]
