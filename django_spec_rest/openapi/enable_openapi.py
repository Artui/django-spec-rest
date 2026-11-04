"""Opt-in helper that wires
[`ServiceAutoSchema`][django_spec_rest.openapi.service_auto_schema.ServiceAutoSchema]
onto every library view."""

from __future__ import annotations

from typing import Any, cast


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
    - ``ServiceCreateMixin``, ``ServiceUpdateMixin``, ``ServiceDestroyMixin``,
      ``SelectorListMixin``, ``SelectorRetrieveMixin``

    The function-local imports keep ``drf-spectacular`` an optional
    dependency: importing
    ``django_spec_rest.openapi`` does not require it, and only
    this call brings in the schema-generator code.

    User subclasses inherit ``schema = ServiceAutoSchema()`` automatically;
    classes that set ``schema = ...`` explicitly keep their own choice. A
    project's ``GenericViewSet`` composed of the mixins inherits it only where
    a mixin comes before ``GenericViewSet`` in its bases, since DRF's
    ``APIView`` carries a ``schema`` of its own
    (test_the_documented_setup's
    test_a_mixin_listed_first_documents_its_spec_with_no_schema_of_its_own).

    Where a mixin does come first, its ``ServiceAutoSchema`` also wins over a
    project's ``DEFAULT_SCHEMA_CLASS``, even a subclass of it; setting
    ``schema = ProjectSchema()`` on the class keeps the subclass
    (test_the_documented_setup's
    test_a_mixin_listed_first_overrides_a_project_s_default_schema_class).

    It also inserts
    [`reserved_components_hook`][django_spec_rest.openapi.reserved_components_hook.reserved_components_hook]
    first in drf-spectacular's ``POSTPROCESSING_HOOKS``, before the project's
    own hooks and once however often it is called, so a component of the
    project's under a name the package documents its refusals by is refused
    on any view. It recognises the package's own references by the identity
    of their ``$ref`` strings, so a project hook that rebuilds those strings
    (a JSON round trip) must run after it, not before.
    """
    # Local imports per CLAUDE.md "Lazy / function-local imports are
    # forbidden unless... a proven optional dependency": ``drf-spectacular``
    # is exactly that.
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

    # Declared loosely: the mixins carry no ``schema`` of their own, which
    # arrives with ``APIView`` when a project composes them.
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
    # Inserted first, and only where absent, so a repeated call, or a project
    # listing the hook itself, runs it once (test_enable_openapi's
    # test_the_hook_is_installed_once). First because it tells the package's
    # own references from a project's by identity: a project hook that
    # rebuilds the strings, run before it, would make every reference look foreign
    # (test_reserved_components_hook's test_a_copying_hook_of_the_project_runs_after_it).
    if reserved_components_hook not in hooks:
        hooks.insert(0, reserved_components_hook)
