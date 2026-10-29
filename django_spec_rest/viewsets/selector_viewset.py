"""Read-only viewset composed of selector + action-serializer-resolver mixins."""

from __future__ import annotations

from rest_framework.viewsets import GenericViewSet

from django_spec_rest.viewsets.action_serializer_resolver import (
    ActionSerializerResolver,
)
from django_spec_rest.viewsets.selector_list_mixin import SelectorListMixin
from django_spec_rest.viewsets.selector_retrieve_mixin import (
    SelectorRetrieveMixin,
)


class SelectorViewSet(
    SelectorListMixin,
    SelectorRetrieveMixin,
    ActionSerializerResolver,
    GenericViewSet,
):
    """Read-only viewset for ``list`` + ``retrieve``.

    Composes
    [`SelectorListMixin`][django_spec_rest.viewsets.selector_list_mixin.SelectorListMixin],
    [`SelectorRetrieveMixin`][django_spec_rest.viewsets.selector_retrieve_mixin.SelectorRetrieveMixin],
    and
    [`ActionSerializerResolver`][django_spec_rest.viewsets.action_serializer_resolver.ActionSerializerResolver]
    over ``GenericViewSet``."""
