"""The author's values for a service outrank every key its Validator hands back, on the kernel route.

The spec's ``kwargs`` provider is the server's, and the kernel merges its
answer into the service's pool after the validated values, so a service is
handed the provider's value for a keyword over anything the client's input
became: a key a serializer's ``validate()`` derives from the body, or one a
``source="*"`` nested serializer flattens into ``validated_data``. The
client's value stays where it was validated, in ``data``.

A view's ``get_service_kwargs`` hook, the other author, outranks the Validator
too, as on drfs: the edge lays the hook's values beneath the spec's provider in
its seat rather than in the kernel's overlay, which sits beneath what the
Validator computes. Beneath the provider it answers as the kernel's overlay
does: the provider's value wins a key both give, a key a typed provider owns is
never the hook's, and one it declines falls to the hook.

Not ported: drfs kept the bound serializer over an author's value named
``serializer``. On the kernel route the ``kwargs`` provider's answer is merged
after what the Validator binds, so a provider key of that name replaces the
bound serializer. Only the author's own values meet there, never a client's,
so it is no server-value gap; the kernel could refuse such a key as it refuses
one named like a seed, and that is a kernel ask rather than a test here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest
from django_service_specs import UNSET, ServiceSpec, UnsetType
from rest_framework import serializers
from typing_extensions import TypedDict

from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.views.server_value_calls import CORES, OPEN, Core, post
from tests.views.test_kernel_views import _CreateView

pytestmark = pytest.mark.django_db


class _DerivingIn(serializers.Serializer):
    """A ``validate()`` that turns a client's field into a key no field declares."""

    title = serializers.CharField()
    claimed = serializers.CharField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "claimed" in attrs:
            attrs["tenant_id"] = attrs.pop("claimed")
        return attrs


class _TenantPart(serializers.Serializer):
    tenant_id = serializers.CharField(required=False)


class _FlatteningIn(serializers.Serializer):
    """A ``source="*"`` nested serializer, whose fields land at the top of ``validated_data``."""

    title = serializers.CharField()
    meta = _TenantPart(source="*", required=False)


# Each body carries only what its serializer declares: under ``REJECT`` the
# other serializer's key would be an unknown argument, not a second route.
_SHAPES = {
    "validate": (_DerivingIn, {"title": "t", "claimed": "evil"}),
    "star": (_FlatteningIn, {"title": "t", "meta": {"tenant_id": "evil"}}),
}
_SHAPE = pytest.mark.parametrize(("serializer", "body"), _SHAPES.values(), ids=_SHAPES.keys())


class _Tenant(TypedDict):
    tenant_id: str


def _untyped_provider() -> dict[str, Any]:
    return {"tenant_id": "server"}


def _typed_provider() -> _Tenant:
    return {"tenant_id": "server"}


_PROVIDER = pytest.mark.parametrize(
    "provider", [_untyped_provider, _typed_provider], ids=["untyped", "typed"]
)
_OUTRANKED = {"tenant_id": "server", "data": {"title": "t", "tenant_id": "evil"}}


def _recording(seen: dict[str, Any]) -> Callable[..., None]:
    def service(*, data: Any, tenant_id: str = "none") -> None:
        seen["tenant_id"] = tenant_id
        seen["data"] = dict(data)

    return service


def _spec(seen: dict[str, Any], serializer: Any, **fields: Any) -> ServiceSpec:
    return ServiceSpec(
        service=_recording(seen),
        permissions=OPEN,
        validator=SerializerValidator(serializer),
        atomic=False,
        **fields,
    )


@_SHAPE
@_PROVIDER
def test_the_specs_provider_outranks_the_validators_over_http(
    serializer: Any, body: dict[str, Any], provider: Callable[..., Any]
) -> None:
    seen: dict[str, Any] = {}

    response = post(_spec(seen, serializer, kwargs=provider), body)

    assert response.status_code == 204, response.data
    assert seen == _OUTRANKED


@CORES
@_SHAPE
@_PROVIDER
def test_the_specs_provider_outranks_the_validators_on_either_core(
    core: Core, serializer: Any, body: dict[str, Any], provider: Callable[..., Any]
) -> None:
    seen: dict[str, Any] = {}

    core(_spec(seen, serializer, kwargs=provider), body)

    assert seen == _OUTRANKED


def _hooked(value: Any) -> type[_CreateView]:
    class _Hooked(_CreateView):
        def get_service_kwargs(self) -> dict[str, Any]:
            return {"tenant_id": value}

    return _Hooked


@_SHAPE
def test_a_view_hooks_value_outranks_the_validators_over_http(
    serializer: Any, body: dict[str, Any]
) -> None:
    seen: dict[str, Any] = {}

    response = post(_spec(seen, serializer), body, view=_hooked("server"))

    assert response.status_code == 204, response.data
    assert seen == _OUTRANKED


@_SHAPE
def test_the_spec_s_provider_outranks_a_view_hook_for_one_key(
    serializer: Any, body: dict[str, Any]
) -> None:
    seen: dict[str, Any] = {}

    response = post(_spec(seen, serializer, kwargs=_untyped_provider), body, view=_hooked("hook"))

    assert response.status_code == 204, response.data
    assert seen == _OUTRANKED


class _MayFill(TypedDict, total=False):
    tenant_id: str | UnsetType


def _owns_and_declines() -> _Tenant:
    return cast(_Tenant, {"tenant_id": UNSET})


def _may_decline() -> _MayFill:
    return {"tenant_id": UNSET}


def test_a_key_the_typed_provider_owns_is_never_a_view_hook_s() -> None:
    """The provider owns ``tenant_id`` and declines it, so it is absent: neither
    the hook's value nor the client's, which ``validate()`` derived."""
    seen: dict[str, Any] = {}
    spec = _spec(seen, _DerivingIn, kwargs=_owns_and_declines)

    response = post(spec, _SHAPES["validate"][1], view=_hooked("hook"))

    assert response.status_code == 204, response.data
    assert seen["tenant_id"] == "none"


def test_a_key_the_provider_declines_falls_to_a_view_hook() -> None:
    seen: dict[str, Any] = {}
    spec = _spec(seen, _DerivingIn, kwargs=_may_decline)

    response = post(spec, _SHAPES["validate"][1], view=_hooked("server"))

    assert response.status_code == 204, response.data
    assert seen == _OUTRANKED


def test_a_view_hook_s_unset_supplies_nothing() -> None:
    """A hook's ``UNSET`` is no value, so the Validator's stands."""
    seen: dict[str, Any] = {}

    response = post(_spec(seen, _DerivingIn), _SHAPES["validate"][1], view=_hooked(UNSET))

    assert response.status_code == 204, response.data
    assert seen["tenant_id"] == "evil"


@CORES
def test_an_authors_serializer_value_reaches_a_service_no_validator_binds_one_for(
    core: Core,
) -> None:
    seen: dict[str, Any] = {}

    def service(*, serializer: Any = "default", tenant_id: str = "none") -> None:
        seen["serializer"] = serializer
        seen["tenant_id"] = tenant_id

    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        kwargs=lambda: {"serializer": "provider", "tenant_id": "server"},
        atomic=False,
    )

    core(spec, {})

    assert seen == {"serializer": "provider", "tenant_id": "server"}


@CORES
def test_a_required_parameter_only_the_provider_fills_is_filled(core: Core) -> None:
    """An untyped provider's value fills a service keyword with no default,
    which no argument the caller sends could fill."""
    seen: dict[str, Any] = {}

    def close(*, reason: str) -> None:
        seen["reason"] = reason

    spec = ServiceSpec(
        service=close, permissions=OPEN, kwargs=lambda: {"reason": "server"}, atomic=False
    )

    core(spec, {})

    assert seen == {"reason": "server"}


def test_a_hook_s_key_a_typed_provider_does_not_list_still_reaches_the_service() -> None:
    """The hook's values join the typed provider's answer in its seat, where a
    key its ``TypedDict`` does not list is the hook's to add, as in the
    kernel's overlay."""
    seen: dict[str, Any] = {}

    def service(*, data: Any, tenant_id: str = "none", note: str = "none") -> None:
        seen.update(tenant_id=tenant_id, note=note)

    class _Noted(_CreateView):
        def get_service_kwargs(self) -> dict[str, Any]:
            return {"note": "hook"}

    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        validator=SerializerValidator(_DerivingIn),
        kwargs=_typed_provider,
        atomic=False,
    )

    response = post(spec, {"title": "t"}, view=_Noted)

    assert response.status_code == 204, response.data
    assert seen == {"tenant_id": "server", "note": "hook"}
