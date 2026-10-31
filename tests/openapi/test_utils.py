"""Unit tests for ``openapi.utils.default_status``."""

from __future__ import annotations

from typing import Any

import pytest

from django_spec_rest import (
    ServiceCreateView,
    ServiceDeleteView,
    ServiceUpdateView,
)
from django_spec_rest.openapi.utils import default_status


def _bound_action(action: str) -> Any:
    class _V: ...

    v = _V()
    v.action = action  # ty: ignore[unresolved-attribute]
    return v


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        pytest.param("create", 201, id="create_action_defaults_to_201"),
        pytest.param("destroy", 204, id="destroy_action_defaults_to_204"),
        pytest.param("partial_update", 200, id="partial_update_defaults_to_200"),
        pytest.param("approve", 200, id="unknown_action_defaults_to_200"),
    ],
)
def test_an_action_s_default_status(action: str, expected: int) -> None:
    assert default_status(_bound_action(action)) == expected


@pytest.mark.parametrize(
    ("view", "expected"),
    [
        pytest.param(ServiceCreateView, 201, id="create"),
        pytest.param(ServiceUpdateView, 200, id="update"),
        pytest.param(ServiceDeleteView, 204, id="delete"),
    ],
)
def test_a_view_class_s_default_status(view: type, expected: int) -> None:
    assert default_status(view()) == expected


def test_unrecognised_view_falls_back_to_200() -> None:
    class _Vanilla: ...

    assert default_status(_Vanilla()) == 200
