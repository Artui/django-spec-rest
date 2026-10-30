"""A typed ``kwargs`` provider over a field whose wire name and ``source`` differ, on the kernel route.

``tenant = CharField(source="org")`` is one value under two names: the client
sends ``tenant``, and ``SerializerValidator`` hands the service ``org``. The
two names answer differently on a kernel spec:

- **The wire name is a Validator parameter**, and the kernel refuses a typed
  ``kwargs`` provider annotated to fill one, since its values reach the
  service's pool and never the Validator; ``input_data`` is the seat that
  fills a field. That refusal is the kernel's, raised when the spec's
  parameters are assembled, so the drfs cases of a provider owning the wire
  name have no kernel counterpart and the refusal is asserted instead.
- **The ``source`` is no parameter**, so a provider may own it, and what the
  service is handed for it is the question the rest of this module asks.
  ``NotClientInput`` on the wire name has no reader on a kernel spec; a
  provider owning the ``source`` is its spelling here.

A view hook naming either name is not asked on the kernel route at all; that
gap is held by ``test_author_values_outrank_the_validator``'s strict xfail.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any, TypedDict

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import ServiceSpec, UnsetType
from django_service_specs.dispatch.check_seeds import check_seeds
from rest_framework import serializers

from django_spec_rest import UNSET
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.views.server_value_calls import CORES, FORMATS, OPEN, Core, post
from tests.views.test_kernel_views import _view

pytestmark = pytest.mark.django_db

# The client's value for a key a provider owns reaches that key's service
# parameter on the kernel route, because ``SerializerValidator`` hands the
# service every validated value by its ``source`` and the kernel spreads it
# into the pool before the provider answers.
_OWNED_GAP = pytest.mark.xfail(
    strict=True,
    reason=(
        "the kernel route sets no provider_owned on the edge's state, so "
        "SerializerValidator hands the client's value for a key the typed "
        "provider owns to the service by its source"
    ),
)


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
_FILLED = {"org": "srv", "tenant": "D-tenant", "data": {"org": "srv"}}


@_OWNED_GAP
@FORMATS
def test_a_declined_owned_source_hands_its_parameter_none_of_the_clients_value(fmt: str) -> None:
    seen: dict[str, Any] = {}

    response = post(_spec(seen, owns="org", value=UNSET), {"tenant": "evil"}, fmt=fmt)

    assert response.status_code == 204, response.data
    assert seen == _DECLINED


@_OWNED_GAP
@CORES
def test_a_declined_owned_source_hands_its_parameter_none_of_the_clients_value_on_either_core(
    core: Core,
) -> None:
    seen: dict[str, Any] = {}

    core(_spec(seen, owns="org", value=UNSET), {"tenant": "evil"})

    assert seen == _DECLINED


@pytest.mark.xfail(
    strict=True,
    reason=(
        "open owner decision: kwargs feeds the callable only, so the provider's "
        "value never reaches data, which keeps the client's"
    ),
)
@FORMATS
def test_a_filled_owned_source_is_the_providers_value_in_data_too(fmt: str) -> None:
    """A typed provider owning a ``source`` no field is named for: a key named
    like a field is ``test_a_kwargs_value_named_like_a_field_is_the_service_s_alone``'s
    (``tests/service_specs/``), and this case waits on the same decision."""
    seen: dict[str, Any] = {}

    response = post(_spec(seen, owns="org", value="srv"), {"tenant": "evil"}, fmt=fmt)

    assert response.status_code == 204, response.data
    assert seen == _FILLED


@FORMATS
def test_a_filled_owned_source_is_the_providers_value_for_its_parameter(fmt: str) -> None:
    """The half the kernel route already gives: the provider's value outranks
    the validated one in the service's pool, and the wire name's parameter,
    which nothing filled, keeps its default."""
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
    """A key the provider may decline is not the server's alone: declined, the
    client's value for it stands, in the parameter and in ``data``, as the
    kernel answers a declinable key everywhere. The owned key's answer above
    is the gap; this is the control that keeps a fix from taking both."""
    seen: dict[str, Any] = {}
    spec = dataclasses.replace(_spec(seen, owns="org", value=UNSET), kwargs=_may_decline_the_source)

    response = post(spec, {"tenant": "evil"}, fmt=fmt)

    assert response.status_code == 204, response.data
    assert seen == {"org": "evil", "tenant": "D-tenant", "data": {"org": "evil"}}


@_OWNED_GAP
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


@_OWNED_GAP
@FORMATS
def test_owning_the_key_a_dotted_source_nests_under_owns_no_deeper_one(fmt: str) -> None:
    """``loc.city`` is nested under ``loc``: a field of its own named ``city`` stays the client's."""
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
