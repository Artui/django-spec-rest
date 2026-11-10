from __future__ import annotations

from typing import Any, cast


def enable_openapi() -> None:
    """Set [`ServiceAutoSchema`][django_spec_rest.openapi.service_auto_schema.ServiceAutoSchema] as the schema on every library view class."""  # noqa: E501
    from drf_spectacular.settings import spectacular_settings

    from django_spec_rest.openapi.reserved_components_hook import (
        reserved_components_hook,
    )
    from django_spec_rest.openapi.service_auto_schema import ServiceAutoSchema
    from django_spec_rest.views.mutation.service_create_view import (
        ServiceCreateView,
    )
    from django_spec_rest.views.mutation.service_delete_view import (
        ServiceDeleteView,
    )
    from django_spec_rest.views.mutation.service_update_view import (
        ServiceUpdateView,
    )
    from django_spec_rest.views.query.selector_list_view import SelectorListView
    from django_spec_rest.views.query.selector_retrieve_view import (
        SelectorRetrieveView,
    )
    from django_spec_rest.viewsets.selector_list_mixin import SelectorListMixin
    from django_spec_rest.viewsets.selector_retrieve_mixin import (
        SelectorRetrieveMixin,
    )
    from django_spec_rest.viewsets.selector_viewset import SelectorViewSet
    from django_spec_rest.viewsets.service_create_mixin import ServiceCreateMixin
    from django_spec_rest.viewsets.service_destroy_mixin import ServiceDestroyMixin
    from django_spec_rest.viewsets.service_update_mixin import ServiceUpdateMixin
    from django_spec_rest.viewsets.service_viewset import ServiceViewSet

    classes = cast(
        "tuple[type[Any], ...]",
        (
            ServiceCreateView,
            ServiceUpdateView,
            ServiceDeleteView,
            SelectorListView,
            SelectorRetrieveView,
            ServiceViewSet,
            SelectorViewSet,
            ServiceCreateMixin,
            ServiceUpdateMixin,
            ServiceDestroyMixin,
            SelectorListMixin,
            SelectorRetrieveMixin,
        ),
    )
    for view_cls in classes:
        view_cls.schema = ServiceAutoSchema()
    hooks = spectacular_settings.POSTPROCESSING_HOOKS
    if reserved_components_hook not in hooks:
        hooks.insert(0, reserved_components_hook)
