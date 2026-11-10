from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import DEFAULT_POOL_SEEDS, PermissionCheck, ServiceSpec
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView
from django_spec_rest.service_specs.serializer_validator import SerializerValidator

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()


class _Row(serializers.Serializer):
    title = serializers.CharField()


class _Counted:
    """The check's asks and the seed's resolutions, counted across one call."""

    def __init__(self) -> None:
        self.asked = 0
        self.resolved = 0

    def seed(self) -> str:
        self.resolved += 1
        return "stamp"


class _StampedCheck(PermissionCheck):
    """A class-level check that counts each ask and names the ``stamp`` seed."""

    def __init__(self, counted: _Counted) -> None:
        self.counted = counted

    def has_permission(self, principal: Any, spec: Any, *, stamp: str) -> bool:
        self.counted.asked += 1
        return stamp == "stamp"


def _post(body: list[Any]) -> tuple[Any, _Counted]:
    counted = _Counted()
    spec = ServiceSpec(
        service=lambda *, data: data,
        permissions=(_StampedCheck(counted),),
        validator=SerializerValidator(_Row),
        many=True,
        atomic=False,
    )
    attrs = {
        "spec": spec,
        "permission_classes": [],
        "authentication_classes": [],
        "pool_seeds": DEFAULT_POOL_SEEDS.extend(stamp=counted.seed),
    }
    view = type("_View", (ServiceCreateView,), attrs).as_view()
    return view(factory.post("/", body, format="json")), counted


def test_a_well_formed_many_call_asks_its_check_and_resolves_its_seed_once() -> None:
    """The contrast: the prelude's grant and seeds reach ``dispatch``, which asks nothing again."""
    response, counted = _post([{"title": "a"}, {"title": "b"}])
    assert response.status_code == 201
    assert (counted.asked, counted.resolved) == (1, 1)


def test_a_many_call_with_a_refused_row_asks_its_check_and_resolves_its_seed_twice() -> None:
    """The prelude hands on no grant and no seeds for a refused row, so ``dispatch`` asks again."""
    response, counted = _post([{"title": "a"}, 5])
    assert response.status_code == 400
    assert list(response.data["items"]) == [1]
    assert (counted.asked, counted.resolved) == (2, 2)
