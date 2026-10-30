"""Tests for views/utils.py."""

from __future__ import annotations

from typing import Any

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
    def test_returns_empty_when_no_layers_present(self) -> None:
        result = resolve_extra_kwargs(
            _BareView(),
            _request(),
            action_hook=None,
            catch_all_hook="get_service_kwargs",
        )
        assert result == {}

    def test_catch_all_hook_only(self) -> None:
        result = resolve_extra_kwargs(
            _ViewWithCatchAll(),
            _request(),
            action_hook=None,
            catch_all_hook="get_service_kwargs",
        )
        assert result == {"a": "catch", "shared": "catch"}

    def test_action_hook_overrides_catch_all(self) -> None:
        result = resolve_extra_kwargs(
            _ViewWithActionHook(),
            _request(),
            action_hook="get_create_service_kwargs",
            catch_all_hook="get_service_kwargs",
        )
        assert result == {"a": "catch", "b": "action", "shared": "action"}

    def test_action_hook_missing_method_falls_back(self) -> None:
        result = resolve_extra_kwargs(
            _ViewWithCatchAll(),
            _request(),
            action_hook="get_nonexistent_service_kwargs",
            catch_all_hook="get_service_kwargs",
        )
        assert result == {"a": "catch", "shared": "catch"}

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
    def test_returns_empty_when_no_layers_present(self) -> None:
        result = resolve_input_extras(
            _BareView(),
            _request(),
            action_hook=None,
            catch_all_hook="get_input_data",
        )
        assert result == {}

    def test_catch_all_hook_only(self) -> None:
        result = resolve_input_extras(
            _ViewWithInputCatchAll(),
            _request(),
            action_hook=None,
            catch_all_hook="get_input_data",
        )
        assert result == {"a": "catch", "shared": "catch"}

    def test_action_hook_overrides_catch_all(self) -> None:
        result = resolve_input_extras(
            _ViewWithInputAction(),
            _request(),
            action_hook="get_create_input_data",
            catch_all_hook="get_input_data",
        )
        assert result == {"a": "catch", "b": "action", "shared": "action"}

    def test_action_hook_missing_method_falls_back(self) -> None:
        result = resolve_input_extras(
            _ViewWithInputCatchAll(),
            _request(),
            action_hook="get_nonexistent_input_data",
            catch_all_hook="get_input_data",
        )
        assert result == {"a": "catch", "shared": "catch"}

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
