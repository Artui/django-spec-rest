from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.test import RequestFactory
from django_service_specs import (
    DEFAULT_POOL_SEEDS,
    SelectorKind,
    SelectorSpec,
    Unrestricted,
    dispatch,
)
from django_service_specs.pool.base_pool import base_pool
from rest_framework.request import Request

from django_spec_rest import build_offline_context

_RECIPE = Path(__file__).parents[2] / "docs" / "recipes" / "off-http-inputs.md"
_USER = User(username="principal")
_SEEN: dict[str, Any] = {}


def drf_request(*, user, request):
    return build_offline_context(user, http_request=request).request


_SEEDS = DEFAULT_POOL_SEEDS.extend(request=drf_request)


def _reads_the_query_string(*, request: Any) -> list[Any]:
    _SEEN["request"] = request
    return [request.query_params.get("status", "any")]


_SPEC = SelectorSpec(
    kind=SelectorKind.LIST, selector=_reads_the_query_string, permissions=(Unrestricted(),)
)


def _dispatched(http_request: HttpRequest | None) -> Any:
    return dispatch(
        _SPEC,
        principal=_USER,
        arguments={},
        pool_seeds=_SEEDS,
        call_context={"request": http_request, "view": None},
    )


def test_the_recipe_shows_this_seed() -> None:
    assert inspect.getsource(drf_request) in _RECIPE.read_text()
    assert "DEFAULT_POOL_SEEDS.extend(request=drf_request)" in _RECIPE.read_text()


def test_the_call_s_django_request_has_no_query_params() -> None:
    """What the seed is for: a selector reading them raises without it."""
    http_request = RequestFactory().post("/mcp/")
    with pytest.raises(AttributeError, match="query_params"):
        dispatch(
            _SPEC,
            principal=_USER,
            arguments={},
            call_context={"request": http_request, "view": None},
        )


def test_a_selector_reading_query_params_is_handed_a_drf_request() -> None:
    http_request = RequestFactory().post("/mcp/")
    assert _dispatched(http_request).value == ["any"]
    assert isinstance(_SEEN["request"], Request)
    assert _SEEN["request"].user is _USER


def test_its_query_params_are_the_endpoint_s() -> None:
    assert _dispatched(RequestFactory().post("/mcp/?status=paid")).value == ["paid"]


def test_the_call_s_own_request_is_untouched() -> None:
    http_request = RequestFactory().get("/mcp/")
    _dispatched(http_request)
    assert http_request.method == "GET"
    assert not hasattr(http_request, "user")


def test_a_fixed_value_goes_in_through_query_params() -> None:
    def fixed(*, user: Any, request: Any) -> Any:
        return build_offline_context(
            user, http_request=request, query_params={"status": "sent"}
        ).request

    answered = dispatch(
        _SPEC,
        principal=_USER,
        arguments={},
        pool_seeds=DEFAULT_POOL_SEEDS.extend(request=fixed),
        call_context={"request": RequestFactory().post("/mcp/"), "view": None},
    )
    assert answered.value == ["sent"]


def test_a_call_with_no_request_is_handed_one_too() -> None:
    assert _dispatched(None).value == ["any"]
    assert _SEEN["request"].user is _USER


def test_a_pool_spreading_its_own_request_beside_the_seed_is_refused() -> None:
    """What a view resource's read does until ``django-spec-mcp`` builds its pool otherwise."""
    with pytest.raises(TypeError, match="registered pool seed 'request'"):
        base_pool(user=_USER, request=RequestFactory().post("/mcp/"), seeds=_SEEDS)
