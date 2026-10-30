"""django-spec-rest: kernel specs served over Django REST Framework.

Public API re-exports live here. Importing the top-level package is enough
for typical usage; deeper imports (``django_spec_rest.types``,
``django_spec_rest.views``, ``django_spec_rest.viewsets``) are stable and
supported. A spec itself, and everything the kernel owns, is imported from
``django_service_specs``.
"""

from django_spec_rest.service_specs.base_serializer_context import base_serializer_context
from django_spec_rest.service_specs.build_offline_context import build_offline_context
from django_spec_rest.service_specs.renderable_serializer_class import (
    renderable_serializer_class,
)
from django_spec_rest.types import (
    DEFAULT_JSON_SCHEMA_REGISTRY,
    MARKING,
    HttpExtras,
    JsonSchemaRegistry,
    OfflineContext,
    OfflineHttpRequest,
    OfflineServiceView,
    ServiceView,
    ViewHooks,
)
from django_spec_rest.version import __version__
from django_spec_rest.views import (
    SelectorListView,
    SelectorRetrieveView,
    ServiceCreateView,
    ServiceDeleteView,
    ServiceUpdateView,
)
from django_spec_rest.views.mutation.mutation_flow_mixin import MutationFlowMixin
from django_spec_rest.views.mutation.utils import resolve_mutation_instance
from django_spec_rest.viewsets import (
    ActionSerializerResolver,
    SelectorListMixin,
    SelectorRetrieveMixin,
    SelectorViewSet,
    ServiceCreateMixin,
    ServiceDestroyMixin,
    ServiceUpdateMixin,
    ServiceViewSet,
    selector_action,
    service_action,
)

__all__ = [
    "DEFAULT_JSON_SCHEMA_REGISTRY",
    "MARKING",
    "ActionSerializerResolver",
    "HttpExtras",
    "JsonSchemaRegistry",
    "MutationFlowMixin",
    "OfflineContext",
    "OfflineHttpRequest",
    "OfflineServiceView",
    "SelectorListMixin",
    "SelectorListView",
    "SelectorRetrieveMixin",
    "SelectorRetrieveView",
    "SelectorViewSet",
    "ServiceCreateMixin",
    "ServiceCreateView",
    "ServiceDeleteView",
    "ServiceDestroyMixin",
    "ServiceUpdateMixin",
    "ServiceUpdateView",
    "ServiceView",
    "ServiceViewSet",
    "ViewHooks",
    "base_serializer_context",
    "build_offline_context",
    "renderable_serializer_class",
    "resolve_mutation_instance",
    "selector_action",
    "service_action",
]
