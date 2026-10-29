"""Router-compatible viewsets, action mixins, and the ``@service_action`` decorator."""

from django_spec_rest.viewsets.action_serializer_resolver import (
    ActionSerializerResolver,
)
from django_spec_rest.viewsets.decorators import selector_action, service_action
from django_spec_rest.viewsets.selector_list_mixin import SelectorListMixin
from django_spec_rest.viewsets.selector_retrieve_mixin import (
    SelectorRetrieveMixin,
)
from django_spec_rest.viewsets.selector_viewset import SelectorViewSet
from django_spec_rest.viewsets.service_create_mixin import ServiceCreateMixin
from django_spec_rest.viewsets.service_destroy_mixin import ServiceDestroyMixin
from django_spec_rest.viewsets.service_update_mixin import ServiceUpdateMixin
from django_spec_rest.viewsets.service_viewset import ServiceViewSet

__all__ = [
    "ActionSerializerResolver",
    "SelectorListMixin",
    "SelectorRetrieveMixin",
    "SelectorViewSet",
    "ServiceCreateMixin",
    "ServiceDestroyMixin",
    "ServiceUpdateMixin",
    "ServiceViewSet",
    "selector_action",
    "service_action",
]
