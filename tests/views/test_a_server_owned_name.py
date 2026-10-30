"""A name a ``SerializerValidator`` is told is ``server_owned``, over HTTP.

The client may still send a field of that name: the serializer validates it
into ``data`` as it always did, and the service's parameter of that name keeps
its default, so the client's value never becomes the server's. A field's
``source`` is one value under a second name, so it is owned too, and a dotted
``source`` owns the key its value nests under and no deeper one.
"""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import ServiceSpec
from rest_framework import serializers

from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.views.server_value_calls import FORMATS, OPEN, post
from tests.views.test_kernel_views import _CreateView

pytestmark = pytest.mark.django_db


class _Tenant(serializers.Serializer):
    tenant = serializers.CharField(required=False)
    title = serializers.CharField()


class _TenantIntoOrg(serializers.Serializer):
    tenant = serializers.CharField(source="org", required=False)
    title = serializers.CharField()


class _TenantUnderOrg(serializers.Serializer):
    tenant = serializers.CharField(source="org.name", required=False)
    name = serializers.CharField()


# The names a field of these serializers could hand a parameter under; the rest
# of what a ``**`` service is handed is the call's pool.
_NAMES = ("tenant", "org", "name", "title")


def _spec(serializer: type[serializers.Serializer], seen: dict[str, Any]) -> ServiceSpec:
    def service(*, data: Any, **pool: Any) -> None:
        values = {name: pool[name] for name in _NAMES if name in pool}
        seen.update(data=dict(data), values=values)

    return ServiceSpec(
        service=service,
        permissions=OPEN,
        validator=SerializerValidator(serializer, server_owned=frozenset({"tenant"})),
        atomic=False,
    )


@FORMATS
def test_the_clients_value_for_an_owned_name_is_data_and_never_the_parameter(fmt: str) -> None:
    seen: dict[str, Any] = {}

    response = post(_spec(_Tenant, seen), {"tenant": "evil", "title": "t"}, fmt=fmt)

    assert response.status_code == 204, response.data
    assert seen == {"data": {"tenant": "evil", "title": "t"}, "values": {"title": "t"}}


@FORMATS
def test_an_owned_name_owns_its_fields_source(fmt: str) -> None:
    """The client sends ``tenant`` and ``validated_data`` keys it ``org``: neither
    parameter is the client's."""
    seen: dict[str, Any] = {}

    response = post(_spec(_TenantIntoOrg, seen), {"tenant": "evil", "title": "t"}, fmt=fmt)

    assert response.status_code == 204, response.data
    assert seen == {"data": {"org": "evil", "title": "t"}, "values": {"title": "t"}}


def test_a_dotted_source_owns_the_key_it_nests_under_and_no_deeper_one() -> None:
    """``org`` holds the client's ``tenant`` and is owned; ``name``, a key as deep as
    the dotted source reaches, is another field's and stays the client's."""
    seen: dict[str, Any] = {}

    response = post(_spec(_TenantUnderOrg, seen), {"tenant": "evil", "name": "n"})

    assert response.status_code == 204, response.data
    assert seen == {"data": {"org": {"name": "evil"}, "name": "n"}, "values": {"name": "n"}}


@FORMATS
def test_the_servers_value_for_an_owned_name_reaches_its_source(fmt: str) -> None:
    """Where the server put the owned field's value, the key it is handed under is
    the server's to keep, though it is the owned name's ``source``: what is kept
    comes off the owned set after the ``source`` is added to it."""
    seen: dict[str, Any] = {}
    hooked = type("_Hooked", (_CreateView,), {"get_input_data": lambda self, *_: {"tenant": "srv"}})

    response = post(
        _spec(_TenantIntoOrg, seen), {"tenant": "evil", "title": "t"}, fmt=fmt, view=hooked
    )

    assert response.status_code == 204, response.data
    assert seen == {"data": {"org": "srv", "title": "t"}, "values": {"org": "srv", "title": "t"}}
