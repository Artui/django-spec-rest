"""Tests for views/utils.py."""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs.types.unset import UNSET
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from django_spec_rest.views.utils import (
    resolve_callable_kwargs,
    resolve_extra_kwargs,
    resolve_input_extras,
)


def test_passes_only_declared_params() -> None:
    def fn(*, a: int, b: int) -> int:
        return a + b

    pool = {"a": 1, "b": 2, "c": 3}
    assert resolve_callable_kwargs(fn, pool) == {"a": 1, "b": 2}


def test_passes_everything_when_var_keyword_present() -> None:
    def fn(**kwargs: object) -> dict[str, object]:
        return kwargs

    pool = {"a": 1, "b": 2}
    assert resolve_callable_kwargs(fn, pool) == pool


def test_pool_missing_keys_simply_omits() -> None:
    def fn(*, a: int, b: int = 0) -> int:
        return a + b

    pool = {"a": 1}
    assert resolve_callable_kwargs(fn, pool) == {"a": 1}


def test_positional_or_keyword_params_resolved() -> None:
    def fn(a: int, b: int) -> int:
        return a + b

    pool = {"a": 1, "b": 2, "c": 3}
    assert resolve_callable_kwargs(fn, pool) == {"a": 1, "b": 2}


def test_var_positional_ignored() -> None:
    def fn(*args: int, b: int) -> int:
        return b + sum(args)

    pool = {"args": (1, 2), "b": 3}
    # *args is VAR_POSITIONAL, not collected as a kwarg.
    assert resolve_callable_kwargs(fn, pool) == {"b": 3}


_factory = APIRequestFactory()


def _request() -> Request:
    return Request(_factory.get("/"))


class _ViewWithCatchAll:
    def get_service_kwargs(self) -> dict[str, Any]:
        return {"a": "catch", "shared": "catch"}


class _ViewWithActionHook(_ViewWithCatchAll):
    def get_create_service_kwargs(self) -> dict[str, Any]:
        return {"b": "action", "shared": "action"}


class _BareView: ...


class TestResolveExtraKwargs:
    def test_provider_declines_a_key_with_unset(self) -> None:
        # A provider returning ``UNSET`` for a key is declining it — the key is
        # dropped, so an earlier layer's real value survives instead of being
        # overwritten by a sentinel.
        class _View(_ViewWithCatchAll):
            def get_create_service_kwargs(self) -> dict[str, Any]:
                return {"shared": UNSET, "kept": "value"}

        result = resolve_extra_kwargs(
            _View(),
            _request(),
            action_hook="get_create_service_kwargs",
            catch_all_hook="get_service_kwargs",
        )
        assert result == {"a": "catch", "shared": "catch", "kept": "value"}


class _ViewWithInputCatchAll:
    def get_input_data(self, request: Request) -> dict[str, Any]:
        return {"a": "catch", "shared": "catch"}


class _ViewWithInputAction(_ViewWithInputCatchAll):
    def get_create_input_data(self, request: Request) -> dict[str, Any]:
        return {"b": "action", "shared": "action"}


class TestResolveInputExtras:
    def test_extras_offered_only_to_providers_that_declare_them(self) -> None:
        sentinel = object()

        class _View:
            def get_input_data(self, request: Request, *, instance: Any) -> dict[str, Any]:
                return {"hook_instance": instance}

            def get_update_input_data(self, request: Request) -> dict[str, Any]:
                return {"legacy": "untouched"}

        result = resolve_input_extras(
            _View(),
            _request(),
            action_hook="get_update_input_data",
            catch_all_hook="get_input_data",
            extras={"instance": sentinel},
        )
        assert result == {
            "hook_instance": sentinel,
            "legacy": "untouched",
        }


_HOOKS = {
    "service_kwargs": (resolve_extra_kwargs, _ViewWithCatchAll, _ViewWithActionHook),
    "input_data": (resolve_input_extras, _ViewWithInputCatchAll, _ViewWithInputAction),
}


@pytest.mark.parametrize("hook", list(_HOOKS))
@pytest.mark.parametrize(
    ("layers", "action", "expected"),
    [
        pytest.param("none", None, {}, id="returns_empty_when_no_layers_present"),
        pytest.param(
            "catch_all", None, {"a": "catch", "shared": "catch"}, id="catch_all_hook_only"
        ),
        pytest.param(
            "action",
            "create",
            {"a": "catch", "b": "action", "shared": "action"},
            id="action_hook_overrides_catch_all",
        ),
        pytest.param(
            "catch_all",
            "nonexistent",
            {"a": "catch", "shared": "catch"},
            id="action_hook_missing_method_falls_back",
        ),
    ],
)
def test_an_action_hook_layers_over_the_catch_all(
    hook: str, layers: str, action: str | None, expected: dict[str, Any]
) -> None:
    resolve, catch_all_view, action_view = _HOOKS[hook]
    view = {"none": _BareView, "catch_all": catch_all_view, "action": action_view}[layers]
    result = resolve(
        view(),
        _request(),
        action_hook=None if action is None else f"get_{action}_{hook}",
        catch_all_hook=f"get_{hook}",
    )
    assert result == expected
