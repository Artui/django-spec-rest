"""A ``many`` kernel spec's rows over HTTP: what reaches the service and what is refused.

The kernel validates each row through the spec's
Validator and refuses every failing row in one ``InvalidArguments`` addressed
by the row's index under ``many_argument``. That error tree's shape is the
refusal map's; this module holds which rows are refused and that nothing runs.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import ServiceSpec, Unrestricted
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.views.server_value_calls import dispatch_live, open_spec, post

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()


class _Row(serializers.Serializer):
    title = serializers.CharField(max_length=5)


class _OwnedRow(serializers.Serializer):
    title = serializers.CharField()
    owner = serializers.IntegerField()


class _UserRow(serializers.Serializer):
    title = serializers.CharField()
    user = serializers.IntegerField()


ran: list[Any] = []


def _create(*, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ran.append(data)
    return [dict(row) for row in data]


@pytest.fixture(autouse=True)
def _nothing_ran() -> None:
    ran.clear()


def _view(row: type = _Row, **attrs: Any) -> Any:
    spec = ServiceSpec(
        service=_create,
        permissions=(Unrestricted(),),
        validator=SerializerValidator(row),
        many=True,
        atomic=False,
    )
    return type("_View", (ServiceCreateView,), {"spec": spec, **attrs}).as_view()


def _post(view: Any, body: Any) -> Any:
    return view(factory.post("/", body, format="json"))


def test_valid_rows_reach_the_service_as_a_list() -> None:
    response = _post(_view(), [{"title": "a"}, {"title": "b"}])
    assert response.status_code == 201
    assert response.data == [{"title": "a"}, {"title": "b"}]


def test_each_failing_row_is_refused_at_its_index_and_nothing_runs() -> None:
    response = _post(_view(), [{"title": "a"}, 5, {"title": "toolong"}, None])
    assert response.status_code == 400
    rows = response.data["items"]
    assert sorted(rows) == [1, 2, 3]
    assert rows[2]["title"][0].code == "max_length"
    assert ran == []


def test_a_body_that_is_no_list_is_refused_as_a_whole() -> None:
    response = _post(_view(), {"title": "a"})
    assert response.status_code == 400
    assert response.data["items"][0].code == "not_a_list"


def test_the_view_s_input_data_goes_over_each_row() -> None:
    view = _view(_OwnedRow, get_input_data=lambda self, request: {"owner": 7})
    response = _post(view, [{"title": "a", "owner": 1}, {"title": "b"}])
    assert response.status_code == 201
    assert response.data == [{"title": "a", "owner": 7}, {"title": "b", "owner": 7}]


def test_a_row_that_is_no_object_is_refused_beside_view_input_data() -> None:
    view = _view(_OwnedRow, get_input_data=lambda self, request: {"owner": 7})
    response = _post(view, [{"title": "a"}, 5])
    assert response.status_code == 400
    assert list(response.data["items"]) == [1]


def test_a_body_that_is_no_list_beside_view_input_data_is_refused_as_without_it() -> None:
    view = _view(_OwnedRow, get_input_data=lambda self, request: {"owner": 7})
    response = _post(view, {"title": "a"})
    assert response.status_code == 400
    assert response.data["items"][0].code == "not_a_list"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "service_specs/serializer_validator.py: a bulk row's writable field named like a "
        "dispatcher seed is an unknown argument, dropped under the edge's IGNORE and so "
        "refused as required; the kernel route holds no per-row body for the Validator "
        "to bind it from"
    ),
)
def test_a_bulk_row_s_writable_user_validates_from_the_body() -> None:
    response = _post(_view(_UserRow), [{"title": "a", "user": 3}])
    assert response.status_code == 201
    assert response.data == [{"title": "a", "user": 3}]


class _DistinctTitles(serializers.ListSerializer):
    """A list-level ``validate()``, which DRF runs once every row it binds is valid."""

    def validate(self, attrs: Any) -> Any:
        if len({row["title"] for row in attrs}) < len(attrs):
            raise serializers.ValidationError("Each title once.")
        return attrs


class _DistinctRow(_Row):
    class Meta:
        list_serializer_class = _DistinctTitles


def test_a_lists_own_checks_judge_the_rows_the_kernel_passed() -> None:
    """The kernel refuses the row that is no object before the Validator binds a
    row, and the Validator binds the rows left, so the list's own ``validate()``
    runs over them and its refusal sits beside the row's, every row keyed by the
    index it was sent at."""
    response = _post(_view(_DistinctRow), [{"title": "a"}, 5, {"title": "a"}])
    assert response.status_code == 400
    rows = response.data["items"]
    assert sorted(rows, key=str) == [1, "non_field_errors"]
    assert rows["non_field_errors"] == ["Each title once."]
    assert ran == []


def _refused(call: Callable[..., Any]) -> None:
    seen: dict[str, Any] = {}

    def service(*, data: Any, title: Any = None) -> None:
        seen.update(data=data, title=title)

    spec = open_spec(service, _Row, kwargs=lambda: {"title": "from-provider"}, many=True)

    with pytest.raises(ImproperlyConfigured, match=r"answered 'title'.*ServiceSpec\.input_data"):
        call(spec, [{"title": "t"}])

    assert seen == {}


def test_a_kwargs_value_named_like_a_row_field_is_refused() -> None:
    """A ``many`` spec's ``kwargs`` provider is held to what a single-object
    spec's is: its answer naming a row field's wire name would reach the
    service unvalidated, beside the rows the Validator checked, so the request
    is refused and the service never runs."""
    _refused(post)


def test_a_live_view_s_dispatch_refuses_a_kwargs_value_named_like_a_row_field() -> None:
    _refused(dispatch_live)
