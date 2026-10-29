"""Full-CRUD viewset composed of per-action mixins."""

from __future__ import annotations

from rest_framework.viewsets import GenericViewSet

from django_spec_rest.viewsets.action_serializer_resolver import (
    ActionSerializerResolver,
)
from django_spec_rest.viewsets.selector_list_mixin import SelectorListMixin
from django_spec_rest.viewsets.selector_retrieve_mixin import (
    SelectorRetrieveMixin,
)
from django_spec_rest.viewsets.service_create_mixin import ServiceCreateMixin
from django_spec_rest.viewsets.service_destroy_mixin import ServiceDestroyMixin
from django_spec_rest.viewsets.service_update_mixin import ServiceUpdateMixin


class ServiceViewSet(
    ServiceCreateMixin,
    ServiceUpdateMixin,
    ServiceDestroyMixin,
    SelectorListMixin,
    SelectorRetrieveMixin,
    ActionSerializerResolver,
    GenericViewSet,
):
    """Router-compatible viewset wiring services and selectors.

    Composes
    [`ServiceCreateMixin`][django_spec_rest.viewsets.service_create_mixin.ServiceCreateMixin],
    [`ServiceUpdateMixin`][django_spec_rest.viewsets.service_update_mixin.ServiceUpdateMixin],
    [`ServiceDestroyMixin`][django_spec_rest.viewsets.service_destroy_mixin.ServiceDestroyMixin],
    [`SelectorListMixin`][django_spec_rest.viewsets.selector_list_mixin.SelectorListMixin],
    [`SelectorRetrieveMixin`][django_spec_rest.viewsets.selector_retrieve_mixin.SelectorRetrieveMixin],
    and
    [`ActionSerializerResolver`][django_spec_rest.viewsets.action_serializer_resolver.ActionSerializerResolver]
    over ``GenericViewSet``. See those classes for the configurable attributes."""
