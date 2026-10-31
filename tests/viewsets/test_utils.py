"""The action-spec resolution helpers over kernel specs.

``as_view()`` refuses a kernel spec of the wrong kind under a built-in action,
so the backstops below are reachable only when ``action_specs`` is built or
swapped after the view is wired. Exercised directly for that reason.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import SelectorKind, SelectorSpec, ServiceSpec, Unrestricted

from django_spec_rest.viewsets.utils import (
    resolve_action_selector_spec,
    resolve_action_service_spec,
)

_OPEN = (Unrestricted(),)
_SERVICE = ServiceSpec(service=lambda: None, permissions=_OPEN)
_SELECTOR = SelectorSpec(kind=SelectorKind.LIST, selector=lambda: None, permissions=_OPEN)


def test_a_write_action_resolves_a_kernel_service_spec() -> None:
    assert resolve_action_service_spec({"create": _SERVICE}, "create", "POST") is (_SERVICE)


def test_a_read_action_resolves_a_kernel_selector_spec() -> None:
    assert resolve_action_selector_spec({"list": _SELECTOR}, "list") is _SELECTOR


def test_a_write_action_resolved_to_a_kernel_selector_spec_raises() -> None:
    specs: dict[str, Any] = {"create": _SELECTOR}
    with pytest.raises(ImproperlyConfigured, match="must be a ServiceSpec, got SelectorSpec"):
        resolve_action_service_spec(specs, "create", "POST")


def test_a_read_action_resolved_to_a_kernel_service_spec_raises() -> None:
    specs: dict[str, Any] = {"list": _SERVICE}
    with pytest.raises(ImproperlyConfigured, match="must be a SelectorSpec, got ServiceSpec"):
        resolve_action_selector_spec(specs, "list")
