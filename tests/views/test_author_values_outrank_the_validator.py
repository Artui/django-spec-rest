"""The author's values for a service outrank every key its Validator hands back, on the kernel route.

The spec's ``kwargs`` provider is the server's, and the kernel merges its
answer into the service's pool after the validated values, so a service is
handed the provider's value for a keyword over anything the client's input
became: a key a serializer's ``validate()`` derives from the body, or one a
``source="*"`` nested serializer flattens into ``validated_data``. The
client's value stays where it was validated, in ``data``.

Whether a view's ``get_service_kwargs`` hook, the other author, outranks the
Validator is an open owner decision, and its drfs answer is a strict xfail
below.

Not ported: drfs kept the bound serializer over an author's value named
``serializer``. On the kernel route the ``kwargs`` provider's answer is merged
after what the Validator binds, so a provider key of that name replaces the
bound serializer. Only the author's own values meet there, never a client's,
so it is no server-value gap; the kernel could refuse such a key as it refuses
one named like a seed, and that is a kernel ask rather than a test here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django_service_specs import ServiceSpec
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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "open owner decision: get_service_kwargs reaches the kernel as its "
        "extra_kwargs overlay, which sits beneath what the Validator computed by "
        "the kernel's design, so the validated key outranks the hook's value"
    ),
)
@_SHAPE
def test_a_view_hooks_value_outranks_the_validators_over_http(
    serializer: Any, body: dict[str, Any]
) -> None:
    seen: dict[str, Any] = {}

    class _Hooked(_CreateView):
        def get_service_kwargs(self) -> dict[str, Any]:
            return {"tenant_id": "server"}

    response = post(_spec(seen, serializer), body, view=_Hooked)

    assert response.status_code == 204, response.data
    assert seen == _OUTRANKED


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
