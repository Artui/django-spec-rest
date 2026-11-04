"""Fixtures for the openapi tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from django.test import override_settings

from django_spec_rest import (
    SelectorListMixin,
    SelectorListView,
    SelectorRetrieveMixin,
    SelectorRetrieveView,
    SelectorViewSet,
    ServiceCreateMixin,
    ServiceCreateView,
    ServiceDeleteView,
    ServiceDestroyMixin,
    ServiceUpdateMixin,
    ServiceUpdateView,
    ServiceViewSet,
)
from tests import documented_settings

# The classes ``enable_openapi()`` sets its schema on.
_ENABLED = (
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
)


@pytest.fixture
def documented_setup() -> Iterator[None]:
    """The setup ``docs/openapi.md`` gives a project, as it is before ``enable_openapi()`` runs.

    DRF's ``DEFAULT_SCHEMA_CLASS`` is drf-spectacular's ``AutoSchema``, and the
    library's view classes carry no schema of their own yet: other test
    modules call ``enable_openapi()`` at import, so the schema it set is taken
    off for the test and put back after it.
    """
    saved = {cls: vars(cls)["schema"] for cls in _ENABLED if "schema" in vars(cls)}
    for cls in saved:
        del cls.schema
    try:
        with override_settings(REST_FRAMEWORK=documented_settings.REST_FRAMEWORK):
            yield
    finally:
        for cls, schema in saved.items():
            cls.schema = schema
