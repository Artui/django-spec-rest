from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import SelectorKind, SelectorSpec, Unrestricted

from django_spec_rest import ServiceViewSet
from django_spec_rest.viewsets import GetQuerysetScopeWarning


def test_it_is_shown_by_default() -> None:
    """Python hides a ``DeprecationWarning`` outside ``__main__``; this one must reach a project."""
    assert issubclass(GetQuerysetScopeWarning, UserWarning)
    assert not issubclass(GetQuerysetScopeWarning, DeprecationWarning)


def test_the_report_is_of_this_class() -> None:
    class V(ServiceViewSet):
        action_specs = {
            "list": SelectorSpec(
                kind=SelectorKind.LIST, selector=lambda: [], permissions=(Unrestricted(),)
            )
        }

        def get_queryset(self) -> Any:
            return []

    with pytest.warns(GetQuerysetScopeWarning):
        V.as_view({"get": "list"})
