from __future__ import annotations

import importlib
from types import ModuleType

import pytest

import django_spec_rest as pkg
from django_spec_rest.service_specs.base_serializer_context import base_serializer_context
from django_spec_rest.service_specs.build_offline_context import build_offline_context
from django_spec_rest.service_specs.renderable_serializer_class import renderable_serializer_class
from django_spec_rest.types.discriminated_action import DiscriminatedAction
from django_spec_rest.types.field_marking import MARKING
from django_spec_rest.types.http_extras import HttpExtras
from django_spec_rest.types.json_schema_registry import (
    DEFAULT_JSON_SCHEMA_REGISTRY,
    JsonSchemaRegistry,
)
from django_spec_rest.types.offline_context import OfflineContext
from django_spec_rest.types.offline_http_request import OfflineHttpRequest
from django_spec_rest.types.offline_service_view import OfflineServiceView
from django_spec_rest.types.rest_transport import REST_TRANSPORT
from django_spec_rest.types.service_view import ServiceView
from django_spec_rest.types.view_hooks import ViewHooks
from django_spec_rest.views.mutation.mutation_flow_mixin import MutationFlowMixin
from django_spec_rest.views.mutation.service_create_view import ServiceCreateView
from django_spec_rest.views.mutation.service_delete_view import ServiceDeleteView
from django_spec_rest.views.mutation.service_update_view import ServiceUpdateView
from django_spec_rest.views.mutation.utils import resolve_mutation_instance
from django_spec_rest.views.query.selector_list_view import SelectorListView
from django_spec_rest.views.query.selector_retrieve_view import SelectorRetrieveView
from django_spec_rest.viewsets.action_serializer_resolver import ActionSerializerResolver
from django_spec_rest.viewsets.decorators.selector_action import selector_action
from django_spec_rest.viewsets.decorators.service_action import service_action
from django_spec_rest.viewsets.get_queryset_scope_warning import GetQuerysetScopeWarning
from django_spec_rest.viewsets.selector_list_mixin import SelectorListMixin
from django_spec_rest.viewsets.selector_retrieve_mixin import SelectorRetrieveMixin
from django_spec_rest.viewsets.selector_viewset import SelectorViewSet
from django_spec_rest.viewsets.service_create_mixin import ServiceCreateMixin
from django_spec_rest.viewsets.service_destroy_mixin import ServiceDestroyMixin
from django_spec_rest.viewsets.service_update_mixin import ServiceUpdateMixin
from django_spec_rest.viewsets.service_viewset import ServiceViewSet

# Exported name -> the leaf-module original it must alias.
_SURFACE = {
    "ActionSerializerResolver": ActionSerializerResolver,
    "DEFAULT_JSON_SCHEMA_REGISTRY": DEFAULT_JSON_SCHEMA_REGISTRY,
    "DiscriminatedAction": DiscriminatedAction,
    "GetQuerysetScopeWarning": GetQuerysetScopeWarning,
    "HttpExtras": HttpExtras,
    "JsonSchemaRegistry": JsonSchemaRegistry,
    "MARKING": MARKING,
    "REST_TRANSPORT": REST_TRANSPORT,
    "MutationFlowMixin": MutationFlowMixin,
    "OfflineContext": OfflineContext,
    "OfflineHttpRequest": OfflineHttpRequest,
    "OfflineServiceView": OfflineServiceView,
    "SelectorListMixin": SelectorListMixin,
    "SelectorListView": SelectorListView,
    "SelectorRetrieveMixin": SelectorRetrieveMixin,
    "SelectorRetrieveView": SelectorRetrieveView,
    "SelectorViewSet": SelectorViewSet,
    "ServiceCreateMixin": ServiceCreateMixin,
    "ServiceCreateView": ServiceCreateView,
    "ServiceDeleteView": ServiceDeleteView,
    "ServiceDestroyMixin": ServiceDestroyMixin,
    "ServiceUpdateMixin": ServiceUpdateMixin,
    "ServiceUpdateView": ServiceUpdateView,
    "ServiceView": ServiceView,
    "ServiceViewSet": ServiceViewSet,
    "ViewHooks": ViewHooks,
    "base_serializer_context": base_serializer_context,
    "build_offline_context": build_offline_context,
    # A transport that renders an output declaration itself resolves the class
    # through this, or a dataclass output raises there.
    "renderable_serializer_class": renderable_serializer_class,
    "resolve_mutation_instance": resolve_mutation_instance,
    "selector_action": selector_action,
    "service_action": service_action,
}


def test_every_exported_symbol_is_its_leaf_modules_original() -> None:
    for name, original in _SURFACE.items():
        assert getattr(pkg, name) is original, f"{name} diverged from its leaf module"


def test_the_root_exports_exactly_the_names_it_owns() -> None:
    assert sorted(pkg.__all__) == sorted(_SURFACE)


@pytest.mark.parametrize(
    "kernel_name",
    ["ServiceSpec", "SelectorSpec", "dispatch", "NotPermitted", "UNSET"],
)
def test_a_name_the_kernel_owns_is_not_exported(kernel_name: str) -> None:
    assert kernel_name not in pkg.__all__


def test_no_export_is_shadowed_by_its_own_submodule() -> None:
    """Every re-exported name resolves to a value, never to a module object."""
    packages = [
        "django_spec_rest",
        "django_spec_rest.openapi",
        "django_spec_rest.types",
        "django_spec_rest.views",
        "django_spec_rest.viewsets",
    ]
    shadowed: list[str] = []
    for name in packages:
        module = importlib.import_module(name)
        for export in getattr(module, "__all__", ()):
            if isinstance(getattr(module, export), ModuleType):
                shadowed.append(f"{name}.{export}")
    assert shadowed == []
