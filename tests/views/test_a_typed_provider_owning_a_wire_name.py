from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any, TypedDict

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import ServiceSpec, UnsetType
from django_service_specs.dispatch.check_seeds import check_seeds
from django_service_specs.types.unset import UNSET
from rest_framework import serializers

from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.views.server_value_calls import FORMATS, OPEN, dispatch_live, post
from tests.views.test_kernel_views import _view

pytestmark = pytest.mark.django_db


class _SourcedIn(serializers.Serializer):
    tenant = serializers.CharField(source="org", required=False)


def _provider(owns: str, value: Any) -> Callable[[], Any]:
    """A provider annotated to fill ``owns``, answering ``value`` for it."""

    def provider() -> Any:
        return {owns: value}

    provider.__annotations__ = {"return": TypedDict("_Owns", {owns: Any})}
    return provider


def _spec(seen: dict[str, Any], *, owns: str, value: Any) -> ServiceSpec:
    def service(*, data: Any, org: Any = "D-org", tenant: Any = "D-tenant") -> None:
        seen.update(org=org, tenant=tenant, data=dict(data))

    return ServiceSpec(
        service=service,
        permissions=OPEN,
        validator=SerializerValidator(_SourcedIn),
        kwargs=_provider(owns, value),
        atomic=False,
    )


@pytest.mark.parametrize("value", [UNSET, "srv"], ids=["declining", "filling"])
def test_a_provider_owning_the_wire_name_is_refused_with_the_seat_that_fills_it(
    value: Any,
) -> None:
    spec = _spec({}, owns="tenant", value=value)

    with pytest.raises(ImproperlyConfigured, match="Only ServiceSpec.input_data fills"):
        spec.parameters()


def test_a_provider_owning_the_wire_name_is_refused_by_the_kernel_s_mount_check() -> None:
    """``check_seeds``, which a mount will ask of a kernel spec, refuses it in the same words."""
    with pytest.raises(ImproperlyConfigured, match="Only ServiceSpec.input_data fills"):
        check_seeds(_spec({}, owns="tenant", value="srv"))


def test_a_provider_owning_the_wire_name_is_refused_at_as_view() -> None:
    with pytest.raises(ImproperlyConfigured, match="Only ServiceSpec.input_data fills"):
        _view(_spec({}, owns="tenant", value="srv"))


# A provider owning the ``source``: the client's value is the service's in
# ``data`` alone, and the parameter is the provider's answer or its default.
_DECLINED = {"org": "D-org", "tenant": "D-tenant", "data": {"org": "evil"}}
_FILLED = {"org": "srv", "tenant": "D-tenant", "data": {"org": "evil"}}


@FORMATS
def test_a_declined_owned_source_hands_its_parameter_none_of_the_clients_value(fmt: str) -> None:
    seen: dict[str, Any] = {}

    response = post(_spec(seen, owns="org", value=UNSET), {"tenant": "evil"}, fmt=fmt)

    assert response.status_code == 204, response.data
    assert seen == _DECLINED


def test_a_declined_owned_source_hands_its_parameter_none_of_the_clients_value_through_the_edge() -> (  # noqa: E501
    None
):
    seen: dict[str, Any] = {}

    dispatch_live(_spec(seen, owns="org", value=UNSET), {"tenant": "evil"})

    assert seen == _DECLINED


@FORMATS
def test_a_filled_owned_source_feeds_the_callable_and_leaves_data_the_clients(fmt: str) -> None:
    """The decided answer: ``kwargs`` feeds the callable only."""
    seen: dict[str, Any] = {}

    response = post(_spec(seen, owns="org", value="srv"), {"tenant": "evil"}, fmt=fmt)

    assert response.status_code == 204, response.data
    assert seen == _FILLED


@FORMATS
def test_a_filled_owned_source_is_the_providers_value_for_its_parameter(fmt: str) -> None:
    """The half the kernel route already gives."""
    seen: dict[str, Any] = {}

    response = post(_spec(seen, owns="org", value="srv"), {"tenant": "evil"}, fmt=fmt)

    assert response.status_code == 204, response.data
    assert (seen["org"], seen["tenant"]) == ("srv", "D-tenant")


class _NestedIn(serializers.Serializer):
    tenant = serializers.CharField(source="org.name", required=False)


class _BesideItsInnerKey(serializers.Serializer):
    addr = serializers.CharField(source="loc.city", required=False)
    city = serializers.CharField(required=False)


def _may_decline_the_source() -> Any:
    return {"org": UNSET}


_may_decline_the_source.__annotations__ = {
    "return": TypedDict("_MayFillOrg", {"org": str | UnsetType})
}


@FORMATS
def test_a_declinable_source_the_provider_declines_stays_the_clients(fmt: str) -> None:
    """A key the provider may decline is not the server's alone: declined."""
    seen: dict[str, Any] = {}
    spec = dataclasses.replace(_spec(seen, owns="org", value=UNSET), kwargs=_may_decline_the_source)

    response = post(spec, {"tenant": "evil"}, fmt=fmt)

    assert response.status_code == 204, response.data
    assert seen == {"org": "evil", "tenant": "D-tenant", "data": {"org": "evil"}}


@FORMATS
def test_a_dotted_source_s_owned_key_is_the_one_it_nests_under(fmt: str) -> None:
    """``org.name`` is nested under ``org``: the provider owning ``org`` owns the value."""
    seen: dict[str, Any] = {}

    def service(*, data: Any, org: Any = "D-org", tenant: Any = "D-tenant") -> None:
        seen.update(org=org, tenant=tenant, data=dict(data))

    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        validator=SerializerValidator(_NestedIn),
        kwargs=_provider("org", UNSET),
        atomic=False,
    )

    response = post(spec, {"tenant": "evil"}, fmt=fmt)

    assert response.status_code == 204, response.data
    assert seen == {"org": "D-org", "tenant": "D-tenant", "data": {"org": {"name": "evil"}}}


@FORMATS
def test_owning_the_key_a_dotted_source_nests_under_owns_no_deeper_one(fmt: str) -> None:
    """``loc.city`` is nested under ``loc``: a field named ``city`` stays the client's."""
    seen: dict[str, Any] = {}

    def service(*, data: Any, loc: Any = "D-loc", city: Any = "D-city") -> None:
        seen.update(loc=loc, city=city)

    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        validator=SerializerValidator(_BesideItsInnerKey),
        kwargs=_provider("loc", UNSET),
        atomic=False,
    )

    response = post(spec, {"addr": "x", "city": "client"}, fmt=fmt)

    assert response.status_code == 204, response.data
    assert seen == {"loc": "D-loc", "city": "client"}
