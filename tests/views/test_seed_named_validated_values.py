"""A validated key named like a seed stays in ``data`` and never replaces the seed, on the kernel route.

DRF's canonical ``HiddenField(default=CurrentUserDefault())`` named ``user``
validates the principal into ``validated_data["user"]``; a ``validate()`` may
add a key named like any seed. The service is handed ``validated_data`` whole
as ``data``, and each seed under its own name, so the kernel's refusal of a
validated value named like a seed never fires for one ``SerializerValidator``
hands on in ``data`` alone.

Held elsewhere, and so not repeated here:

- a writable field named ``user``, ``result`` or ``serializer`` validating
  from a JSON or a form body while the seed keeps its own value:
  ``test_kernel_views``' ``test_a_writable_field_named_like_a_seed_validates_into_data``
  and ``test_a_seed_named_field_validates_from_a_form_body``;
- the serializer refusing such a field: ``test_a_seed_named_field_the_serializer_refuses_is_drf_s_400``;
- a body that is no object, refused before any field is set aside:
  ``test_a_body_that_is_no_object_is_refused_as_a_whole``;
- a field named like a seed a project registers: the HTTP views register no
  seed of their own, so the case is the kernel's dispatch with a ``PoolSeeds``,
  held by the kernel's
  ``test_a_field_named_like_a_registered_seed_validates_into_data_and_the_pool_keeps_the_seed``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.auth.models import User
from rest_framework import serializers

from tests.views.server_value_calls import FORMATS, dispatch_live, open_spec, post

pytestmark = pytest.mark.django_db


class _CurrentUserIn(serializers.Serializer):
    title = serializers.CharField()
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())


class _AddsSeedsIn(serializers.Serializer):
    """A ``validate()`` adding keys named like three seeds: two the kernel's, one the Validator's."""

    title = serializers.CharField()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        return {**attrs, "result": "added", "progress": "added", "serializer": "added"}


def _record(seen: dict[str, Any]) -> Callable[..., None]:
    def service(*, data: Any, user: Any = None) -> None:
        seen["data"] = dict(data)
        seen["user"] = user

    return service


@FORMATS
def test_a_current_user_hidden_field_named_user_validates_over_http(fmt: str) -> None:
    seen: dict[str, Any] = {}
    alice = User.objects.create(username="alice")

    response = post(open_spec(_record(seen), _CurrentUserIn), {"title": "t"}, fmt=fmt, user=alice)

    assert response.status_code == 204, response.data
    assert seen == {"data": {"title": "t", "user": alice}, "user": alice}


def test_a_current_user_hidden_field_named_user_validates_on_either_core() -> None:
    seen: dict[str, Any] = {}
    alice = User.objects.create(username="alice")

    dispatch_live(open_spec(_record(seen), _CurrentUserIn), {"title": "t"}, user=alice)

    assert seen["data"] == {"title": "t", "user": alice}
    assert seen["user"] == alice


def test_keys_a_validate_adds_named_like_seeds_stay_in_data() -> None:
    seen: dict[str, Any] = {}

    def service(*, data: Any, serializer: Any, progress: Any) -> None:
        seen.update(data=dict(data), serializer=serializer, progress=progress)

    dispatch_live(open_spec(service, _AddsSeedsIn), {"title": "t"})

    assert seen["data"] == {
        "title": "t",
        "result": "added",
        "progress": "added",
        "serializer": "added",
    }
    # The seeds, never the validated values: the call's reporter and the bound serializer.
    assert seen["progress"] != "added"
    assert isinstance(seen["serializer"], _AddsSeedsIn)


def test_each_rows_seed_named_key_stays_in_its_row() -> None:
    seen: dict[str, Any] = {}
    alice = User.objects.create(username="alice")

    def bulk(*, data: Any, user: Any) -> None:
        seen["data"] = [dict(row) for row in data]
        seen["user"] = user

    dispatch_live(
        open_spec(bulk, _CurrentUserIn, many=True),
        [{"title": "a"}, {"title": "b"}],
        user=alice,
    )

    assert seen["data"] == [{"title": "a", "user": alice}, {"title": "b", "user": alice}]
    assert seen["user"] == alice


class _PickedUserIn(serializers.Serializer):
    title = serializers.CharField()
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())


def test_a_writable_field_named_user_is_still_required() -> None:
    """The field is the serializer's to demand, so leaving it out is refused as DRF refuses it."""
    response = post(open_spec(lambda *, data: None, _PickedUserIn), {"title": "t"})

    assert response.status_code == 400
    assert response.data["user"][0].code == "required"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "the kernel route hands a many spec's rows to the kernel as sent, so a "
        "row's seed-named field is an unknown argument there, dropped under the "
        "edge's IGNORE and so refused as required, rather than validated into the row"
    ),
)
def test_a_writable_field_named_user_validates_in_each_row() -> None:
    alice = User.objects.create(username="alice")
    bob = User.objects.create(username="bob")
    seen: dict[str, Any] = {}

    def service(*, data: Any, user: Any) -> None:
        seen["rows"] = [dict(row) for row in data]
        seen["user"] = user

    response = post(
        open_spec(service, _PickedUserIn, many=True), [{"title": "t", "user": bob.pk}], user=alice
    )

    assert response.status_code == 204, response.data
    assert seen == {"rows": [{"title": "t", "user": bob}], "user": alice}
