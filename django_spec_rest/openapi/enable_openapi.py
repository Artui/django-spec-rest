"""Opt-in helper that wires
[`ServiceAutoSchema`][django_spec_rest.openapi.service_auto_schema.ServiceAutoSchema]
onto every library view."""

from __future__ import annotations


def enable_openapi() -> None:
    """Set
    [`ServiceAutoSchema`][django_spec_rest.openapi.service_auto_schema.ServiceAutoSchema]
    as the schema on every library view class.

    Call once from ``AppConfig.ready()`` (or anywhere after Django apps are
    loaded) to make ``drf-spectacular`` see a spec's request bodies, response
    bodies, success statuses, and 422 contracts, a kernel ``ServiceSpec`` or
    ``SelectorSpec`` read off its Validator and presenter, on:

    - ``ServiceCreateView``, ``ServiceUpdateView``, ``ServiceDeleteView``
    - ``SelectorListView``, ``SelectorRetrieveView``
    - ``ServiceViewSet``, ``SelectorViewSet``

    The function-local imports keep ``drf-spectacular`` an optional
    dependency: importing
    ``django_spec_rest.openapi`` does not require it, and only
    this call brings in the schema-generator code.

    User subclasses inherit ``schema = ServiceAutoSchema()`` automatically;
    classes that set ``schema = ...`` explicitly keep their own choice.
    """
    # Local imports per CLAUDE.md "Lazy / function-local imports are
    # forbidden unless... a proven optional dependency": ``drf-spectacular``
    # is exactly that.
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
    from django_spec_rest.viewsets.selector_viewset import SelectorViewSet
    from django_spec_rest.viewsets.service_viewset import ServiceViewSet

    for view_cls in (
        ServiceCreateView,
        ServiceUpdateView,
        ServiceDeleteView,
        SelectorListView,
        SelectorRetrieveView,
        ServiceViewSet,
        SelectorViewSet,
    ):
        view_cls.schema = ServiceAutoSchema()
