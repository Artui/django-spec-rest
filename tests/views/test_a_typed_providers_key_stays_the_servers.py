from __future__ import annotations

from typing import Any, TypedDict, cast

import pytest
from django.contrib.auth.models import AnonymousUser
from django_service_specs import ServiceSpec
from django_service_specs.dispatch.dispatch import dispatch as kernel_dispatch
from django_service_specs.types.unset import UNSET
from rest_framework import serializers

from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.views.server_value_calls import FORMATS, OPEN, dispatch_live, post

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


_SENT = {
    "list": ["a"],
    "nested": {"tenant": "t"},
    "dict": {"k": "v"},
    "many": [{"tenant": "t"}],
    "required": "x",
}


@pytest.mark.parametrize(
    ("serializer", "key", "sent"),
    [(*_FIELDS[name], _SENT[name]) for name in _FIELDS],
    ids=_FIELDS.keys(),
)
def test_a_provider_owning_a_fields_key_leaves_the_field_the_callers(
    serializer: Any, key: str, sent: Any
) -> None:
    """A namesake: the field stays asked for and the client's value is validated into ``data``."""
    seen: dict[str, Any] = {}
    spec = ServiceSpec(
        service=lambda *, data: seen.update(data=dict(data)),
        permissions=OPEN,
        validator=SerializerValidator(serializer),
        kwargs=_declining(key),
        atomic=False,
    )

    response = post(spec, {key: sent})

    assert key in spec.parameters().names()
    assert response.status_code == 204, response.data
    assert seen == {"data": {key: sent}}


def test_a_required_field_a_provider_owns_is_still_demanded_of_the_caller() -> None:
    spec = ServiceSpec(
        service=lambda *, data: None,
        permissions=OPEN,
        validator=SerializerValidator(_RequiredIn),
        kwargs=_declining("title"),
        atomic=False,
    )

    response = post(spec, {})

    assert response.status_code == 400
    assert response.data["title"][0].code == "required"


class _SourcedIn(serializers.Serializer):
    tenant = serializers.CharField(source="org", required=False)


class _OwnsTheSource(TypedDict):
    org: Any


def _declines_the_source() -> _OwnsTheSource:
    return cast(_OwnsTheSource, {"org": UNSET})


@FORMATS
def test_input_data_for_the_field_of_a_declined_source_reaches_its_parameter(fmt: str) -> None:
    """``input_data`` is the server's, so its value for the field is the ``source``'s."""
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


def test_a_kernel_call_inside_the_service_takes_none_of_the_outer_calls_server_values() -> None:
    """The value the outer call's ``input_data`` put is that call's."""
    seen: dict[str, Any] = {}

    def inner(*, data: Any, org: Any = "DEFAULT") -> None:
        seen["inner"] = (org, dict(data))

    inner_spec = ServiceSpec(
        service=inner, permissions=OPEN, validator=SerializerValidator(_SourcedIn), atomic=False
    )

    def outer(*, data: Any) -> None:
        kernel_dispatch(inner_spec, principal=AnonymousUser(), arguments={"tenant": "inner"})

    spec = ServiceSpec(
        service=outer,
        permissions=OPEN,
        validator=SerializerValidator(_SourcedIn),
        input_data=lambda: {"tenant": "srv"},
        atomic=False,
    )

    dispatch_live(spec, {"tenant": "outer"})

    assert seen == {"inner": ("inner", {"org": "inner"})}


def test_a_kernel_call_inside_the_service_keeps_its_own_values() -> None:
    """The keys the outer call's provider owns are that call's."""
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

    dispatch_live(spec, {"tenant": "outer"})

    assert seen == {"inner": "inner"}
