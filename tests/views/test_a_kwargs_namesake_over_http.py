from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict

import pytest
from django_service_specs import ServiceSpec
from rest_framework import serializers

from tests.views.server_value_calls import FORMATS, dispatch_live, open_spec, post
from tests.views.test_kernel_views import _CreateView

pytestmark = pytest.mark.django_db


class _TeamIn(serializers.Serializer):
    team_id = serializers.IntegerField(required=False)
    title = serializers.CharField()


class _Row(serializers.Serializer):
    title = serializers.CharField()


class _Team(TypedDict):
    team_id: int


def _typed() -> _Team:
    return {"team_id": 999}


def _untyped() -> Any:
    return {"team_id": 999}


_PROVIDERS = pytest.mark.parametrize("provider", [_typed, _untyped], ids=["typed", "untyped"])
_BODIES = pytest.mark.parametrize(
    "body",
    [{"title": "x"}, {"team_id": 5, "title": "x"}],
    ids=["field-absent", "field-sent"],
)


def _spec(seen: dict[str, Any], provider: Callable[..., Any]) -> ServiceSpec:
    def service(*, data: Any, team_id: Any) -> None:
        seen.update(team_id=team_id, data=dict(data))

    return open_spec(service, _TeamIn, kwargs=provider)


def _expected(body: dict[str, Any]) -> dict[str, Any]:
    return {"team_id": 999, "data": {**body, "title": "x"}}


@FORMATS
@_PROVIDERS
@_BODIES
def test_a_namesake_is_the_service_s_keyword_and_the_field_stays_the_caller_s(
    fmt: str, provider: Callable[..., Any], body: dict[str, Any]
) -> None:
    seen: dict[str, Any] = {}

    response = post(_spec(seen, provider), body, fmt=fmt)

    assert response.status_code == 204, response.data
    assert seen == _expected(body)


@_PROVIDERS
@_BODIES
def test_a_live_view_s_dispatch_splits_a_namesake_the_same_way(
    provider: Callable[..., Any], body: dict[str, Any]
) -> None:
    seen: dict[str, Any] = {}

    dispatch_live(_spec(seen, provider), body)

    assert seen == _expected(body)


@FORMATS
@_PROVIDERS
@pytest.mark.parametrize(
    ("hooked", "field"), [({"other": 1}, 5), ({"team_id": 7}, 7)], ids=["beside", "on-the-field"]
)
def test_a_namesake_under_a_view_hook_is_still_the_provider_s_keyword(
    fmt: str, provider: Callable[..., Any], hooked: dict[str, Any], field: int
) -> None:
    """The hook's value lies beneath the provider's keyword and over the client's field."""
    seen: dict[str, Any] = {}
    view = type("_Hooked", (_CreateView,), {"get_service_kwargs": lambda self: dict(hooked)})

    response = post(_spec(seen, provider), {"team_id": 5, "title": "x"}, fmt=fmt, view=view)

    assert response.status_code == 204, response.data
    assert seen == {"team_id": 999, "data": {"team_id": field, "title": "x"}}


def test_a_namesake_field_the_caller_sends_is_still_validated() -> None:
    seen: dict[str, Any] = {}

    response = post(_spec(seen, _untyped), {"team_id": "nope", "title": "x"})

    assert response.status_code == 400
    assert "team_id" in response.data
    assert seen == {}


class _Title(TypedDict):
    title: str


def _typed_title() -> _Title:
    return {"title": "from-provider"}


def _untyped_title() -> Any:
    return {"title": "from-provider"}


@pytest.mark.parametrize("call", [post, dispatch_live], ids=["post", "live"])
@pytest.mark.parametrize("provider", [_typed_title, _untyped_title], ids=["typed", "untyped"])
def test_a_many_spec_s_rows_keep_their_field_and_the_keyword_is_the_provider_s(
    call: Callable[..., Any], provider: Callable[..., Any]
) -> None:
    seen: dict[str, Any] = {}

    def service(*, data: Any, title: Any) -> None:
        seen.update(title=title, data=[dict(row) for row in data])

    call(open_spec(service, _Row, kwargs=provider, many=True), [{"title": "a"}, {"title": "b"}])

    assert seen == {"title": "from-provider", "data": [{"title": "a"}, {"title": "b"}]}
