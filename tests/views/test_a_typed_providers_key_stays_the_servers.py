"""A key the spec's typed ``kwargs`` provider is annotated to fill is never the client's, on the kernel route.

On a drfs spec the provider could own any field's key, and declining it left
the service's parameter its default whatever field the client's value came in
through. On a kernel spec the kernel decides most of that before a request
arrives: a key that names a ``SerializerValidator`` parameter - a list, dict,
nested or nested ``many`` field, or a plain required one - is refused when the
spec's parameters are assembled, because the provider's values reach the
service's pool and never the Validator, and ``input_data`` is the seat that
fills a field. So those shapes assert the refusal.

What a provider may still own is a key no field is named for, a ``source``:
whether the client's value reaches it is held by
``test_a_typed_provider_owning_a_wire_name``, and ``input_data`` filling the
field it comes from, and a kernel call inside the service, are held here.
"""

from __future__ import annotations

from typing import Any, TypedDict, cast

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import ServiceSpec
from django_service_specs.dispatch.dispatch import dispatch as kernel_dispatch
from rest_framework import serializers

from django_spec_rest import UNSET
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.views.server_value_calls import CORES, FORMATS, OPEN, Core, post

pytestmark = pytest.mark.django_db


class _Inner(serializers.Serializer):
    tenant = serializers.CharField()


class _ListIn(serializers.Serializer):
    tags = serializers.ListField(child=serializers.CharField(), required=False)


class _NestedIn(serializers.Serializer):
    meta = _Inner(required=False)


class _DictIn(serializers.Serializer):
    d = serializers.DictField(child=serializers.CharField(), required=False)


class _ManyIn(serializers.Serializer):
    rows = _Inner(many=True, required=False)


class _RequiredIn(serializers.Serializer):
    title = serializers.CharField()


_FIELDS = {
    "list": (_ListIn, "tags"),
    "nested": (_NestedIn, "meta"),
    "dict": (_DictIn, "d"),
    "many": (_ManyIn, "rows"),
    "required": (_RequiredIn, "title"),
}


def _declining(key: str) -> Any:
    """A provider annotated to fill ``key``, which declines it."""

    def provider() -> Any:
        return {key: UNSET}

    provider.__annotations__ = {"return": TypedDict("_Keys", {key: Any})}
    return provider


@pytest.mark.parametrize(("serializer", "key"), _FIELDS.values(), ids=_FIELDS.keys())
def test_a_provider_owning_a_fields_key_is_refused_with_the_seat_that_fills_it(
    serializer: Any, key: str
) -> None:
    spec = ServiceSpec(
        service=lambda *, data: None,
        permissions=OPEN,
        validator=SerializerValidator(serializer),
        kwargs=_declining(key),
        atomic=False,
    )

    with pytest.raises(ImproperlyConfigured, match=rf"annotated to fill \['{key}'\]"):
        spec.parameters()


class _SourcedIn(serializers.Serializer):
    tenant = serializers.CharField(source="org", required=False)


class _OwnsTheSource(TypedDict):
    org: Any


def _declines_the_source() -> _OwnsTheSource:
    return cast(_OwnsTheSource, {"org": UNSET})


@FORMATS
def test_input_data_for_the_field_of_a_declined_source_reaches_its_parameter(fmt: str) -> None:
    """``input_data`` is the server's, so its value for the field is the
    ``source``'s, in the parameter and in ``data``, though the provider owning
    the ``source`` declined it."""
    seen: dict[str, Any] = {}

    def service(*, data: Any, org: Any = "DEFAULT") -> None:
        seen.update(param=org, data=dict(data))

    spec = ServiceSpec(
        service=service,
        permissions=OPEN,
        validator=SerializerValidator(_SourcedIn),
        kwargs=_declines_the_source,
        input_data=lambda: {"tenant": "srv"},
        atomic=False,
    )

    response = post(spec, {"tenant": "evil"}, fmt=fmt)

    assert response.status_code == 204, response.data
    assert seen == {"param": "srv", "data": {"org": "srv"}}


@CORES
def test_a_kernel_call_inside_the_service_keeps_its_own_values(core: Core) -> None:
    """The keys the outer call's provider owns are that call's: a spec the
    service dispatches through the kernel hands its own parameter of that name
    the value its own caller sent."""
    seen: dict[str, Any] = {}

    def inner(*, data: Any, org: Any = "DEFAULT") -> None:
        seen["inner"] = org

    inner_spec = ServiceSpec(
        service=inner, permissions=OPEN, validator=SerializerValidator(_SourcedIn), atomic=False
    )

    def outer(*, data: Any) -> None:
        kernel_dispatch(inner_spec, principal=AnonymousUser(), arguments={"tenant": "inner"})

    spec = ServiceSpec(
        service=outer,
        permissions=OPEN,
        validator=SerializerValidator(_SourcedIn),
        kwargs=_declines_the_source,
        atomic=False,
    )

    core(spec, {"tenant": "outer"})

    assert seen == {"inner": "inner"}
