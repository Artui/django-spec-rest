"""The server's value for an input field is the value the server put, however the field reads a body.

On the kernel route the one seat filling a ``SerializerValidator`` field is the
spec's ``input_data``: the kernel merges its answer over the caller's
arguments before the Validator, and the serializer binds what the kernel
hands it. So where a field reads more of a body than its own key - a nested
serializer, a dict, a nested ``many`` or a list a form body fills through
``v.tenant`` or ``v[0]tenant`` - the server's value replaces the client's
whole, and it is what the parameter, ``data`` and ``validated_data`` hold.

A field named like a seed of the call is the serializer's alone, and
``input_data`` naming one is bound over the client's value
(``recording_spec``), so ``data``, ``validated_data`` and the serializer's
``validate()`` all hold the server's value, while the service's parameter of
that name stays the seed's.

The spec's untyped ``kwargs`` provider fills a service keyword and never the
Validator, so its value for a field's name reaches the parameter alone; where
drfs put it into the body too, the case is a strict xfail.

Two answers part from drfs because of how the kernel route reads a body. A
form body's prefixed keys (``v.tenant``) are no parameter to the kernel's flat
reader, so under ``REJECT`` they are refused, a strict xfail, while under
``IGNORE`` they are dropped and the server's value stands. And ``input_data``'s value is bound as the kernel merged it, so a
form body's reading of it (one value for a list, an empty string left out) is
a strict xfail. A field named like a seed a project registers is not ported:
the HTTP views register none, and the kernel's dispatch holds that case.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.auth.models import User
from django_service_specs import ServiceSpec, UnknownArguments
from rest_framework import serializers
from rest_framework.fields import empty

from django_spec_rest.dispatch import kernel_edge
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.views.server_value_calls import CORES, FORMATS, OPEN, Core, post

pytestmark = pytest.mark.django_db

# The kernel's ``kwargs`` provider answers into the service's pool after the
# Validator, so a value it gives for a field's name is the parameter's and
# never reaches ``data`` or ``validated_data``.
_KWARGS_GAP = pytest.mark.xfail(
    strict=True,
    reason=(
        "the kernel route's edge puts none of the kwargs provider's answer into "
        "the serializer's body, so data and validated_data keep the client's value"
    ),
)


def _spec(service: Callable[..., Any], serializer: Any, **fields: Any) -> ServiceSpec:
    return ServiceSpec(
        service=service,
        permissions=OPEN,
        validator=SerializerValidator(serializer),
        atomic=False,
        **fields,
    )


# A field named like a seed of the call: ``user``, the reserved one.

_VALIDATED: list[Any] = []


@pytest.fixture(autouse=True)
def _clear_validated() -> None:
    _VALIDATED.clear()


class _OwnedIn(serializers.Serializer):
    title = serializers.CharField()
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        _VALIDATED.append(attrs["user"])
        return attrs


def _owned(seen: dict[str, Any]) -> Callable[..., None]:
    def service(*, data: Any, serializer: Any, user: Any) -> None:
        seen.update(data=data["user"], validated=serializer.validated_data["user"], user=user)

    return service


def _owner(request: Any) -> dict[str, Any]:
    return {"user": request.user.pk}


@FORMATS
def test_input_data_for_a_field_named_user_outranks_the_clients_over_http(fmt: str) -> None:
    """The server's owner is the one validated, handed on in ``data``, and seen by ``validate()``.

    Beyond ``test_kernel_views``' ``test_the_provider_s_value_outranks_the_client_s``,
    which holds the value over an ``IntegerField``: a related field resolves
    the server's primary key to its row in ``data`` and ``validated_data``
    both, and ``validate()`` runs once, over the server's value alone."""
    alice = User.objects.create(username="alice")
    bob = User.objects.create(username="bob")
    seen: dict[str, Any] = {}
    spec = _spec(_owned(seen), _OwnedIn, input_data=_owner)

    response = post(spec, {"title": "t", "user": bob.pk}, fmt=fmt, user=alice)

    assert response.status_code == 204, response.data
    assert seen == {"data": alice, "validated": alice, "user": alice}
    assert [alice] == _VALIDATED


@CORES
def test_input_data_for_a_field_named_user_outranks_the_clients_on_either_core(core: Core) -> None:
    alice = User.objects.create(username="alice")
    bob = User.objects.create(username="bob")
    seen: dict[str, Any] = {}

    core(
        _spec(_owned(seen), _OwnedIn, input_data=_owner), {"title": "t", "user": bob.pk}, user=alice
    )

    assert seen == {"data": alice, "validated": alice, "user": alice}
    assert [alice] == _VALIDATED


@FORMATS
def test_the_clients_value_for_a_field_named_user_stays_the_fields_with_no_input_data(
    fmt: str,
) -> None:
    """Nothing the server put, so the field validates the client's value; the seed keeps its own.

    The control for the case above, over the same related field and
    ``validate()``; ``test_a_writable_field_named_like_a_seed_validates_into_data``
    holds the plain field."""
    alice = User.objects.create(username="alice")
    bob = User.objects.create(username="bob")
    seen: dict[str, Any] = {}

    response = post(
        _spec(_owned(seen), _OwnedIn), {"title": "t", "user": bob.pk}, fmt=fmt, user=alice
    )

    assert response.status_code == 204, response.data
    assert seen == {"data": bob, "validated": bob, "user": alice}
    assert [bob] == _VALIDATED


# A field that reads more of a form body than its own key.


class _Inner(serializers.Serializer):
    tenant = serializers.CharField(required=False)


class _Nested(serializers.Serializer):
    v = _Inner(required=False)


class _Dict(serializers.Serializer):
    v = serializers.DictField(child=serializers.CharField(), required=False)


class _Many(serializers.Serializer):
    v = _Inner(many=True, required=False)


class _List(serializers.Serializer):
    v = serializers.ListField(child=serializers.CharField(), required=False)


# Each shape: the serializer, the server's value, the client's in a form body
# and in a JSON one.
_READS = {
    "nested": (_Nested, {"tenant": "server"}, {"v.tenant": "evil"}, {"v": {"tenant": "evil"}}),
    "dict": (_Dict, {"k": "server"}, {"v.k": "evil"}, {"v": {"k": "evil"}}),
    "many": (_Many, [{"tenant": "server"}], {"v[0]tenant": "evil"}, {"v": [{"tenant": "evil"}]}),
    "empty-list": (_List, [], {"v[0]": "evil"}, {"v": ["evil"]}),
    "list": (_List, ["server"], {"v[0]": "evil"}, {"v": ["evil"]}),
}
_READ = pytest.mark.parametrize(
    ("serializer", "server", "form", "body"), _READS.values(), ids=_READS.keys()
)


def _reads(seen: dict[str, Any]) -> Callable[..., None]:
    def service(*, data: Any, serializer: Any, v: Any = "default") -> None:
        seen.update(v=v, data=data.get("v"), validated=serializer.validated_data.get("v"))

    return service


@_READ
def test_input_data_is_the_value_put_however_the_field_reads_a_json_body(
    serializer: Any, server: Any, form: dict[str, Any], body: dict[str, Any]
) -> None:
    seen: dict[str, Any] = {}
    spec = _spec(_reads(seen), serializer, input_data=lambda: {"v": server})

    response = post(spec, body)

    assert response.status_code == 204, response.data
    assert seen == {"v": server, "data": server, "validated": server}


@CORES
@_READ
def test_input_data_is_the_value_put_however_the_field_reads_a_json_body_on_either_core(
    core: Core, serializer: Any, server: Any, form: dict[str, Any], body: dict[str, Any]
) -> None:
    seen: dict[str, Any] = {}

    core(_spec(_reads(seen), serializer, input_data=lambda: {"v": server}), body)

    assert seen == {"v": server, "data": server, "validated": server}


# A form body carries a nested or a list field as DRF's prefixed keys -
# ``v.tenant``, ``v[0]tenant``, ``v[0]`` - which are DRF's spelling of the
# declared field ``v``. The kernel's flat reader does not read them, so to the
# kernel they are keys no parameter declares: under ``IGNORE`` they are dropped
# and the server's value is the field's, and under ``REJECT`` the call is
# refused, so no nested or list field can be filled from a form body there.


@pytest.mark.xfail(
    strict=True,
    reason=(
        "the kernel route reads a form body through flat_arguments, which does "
        "not read DRF's prefixed keys for a nested or list field, so under REJECT "
        "they are unknown arguments"
    ),
)
@_READ
def test_input_data_is_the_value_put_over_a_prefixed_form_key_under_reject(
    monkeypatch: pytest.MonkeyPatch,
    serializer: Any,
    server: Any,
    form: dict[str, Any],
    body: dict[str, Any],
) -> None:
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", UnknownArguments.REJECT)
    seen: dict[str, Any] = {}
    spec = _spec(_reads(seen), serializer, input_data=lambda: {"v": server})

    response = post(spec, form, fmt="multipart")

    assert response.status_code == 204, response.data
    assert seen == {"v": server, "data": server, "validated": server}


@_READ
def test_input_data_is_the_value_put_over_a_prefixed_form_key_under_ignore(
    monkeypatch: pytest.MonkeyPatch,
    serializer: Any,
    server: Any,
    form: dict[str, Any],
    body: dict[str, Any],
) -> None:
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", UnknownArguments.IGNORE)
    seen: dict[str, Any] = {}
    spec = _spec(_reads(seen), serializer, input_data=lambda: {"v": server})

    response = post(spec, form, fmt="multipart")

    assert response.status_code == 204, response.data
    assert seen == {"v": server, "data": server, "validated": server}


@_KWARGS_GAP
@_READ
def test_the_providers_value_is_the_one_put_however_the_field_reads_a_json_body(
    serializer: Any, server: Any, form: dict[str, Any], body: dict[str, Any]
) -> None:
    seen: dict[str, Any] = {}
    spec = _spec(_reads(seen), serializer, kwargs=lambda: {"v": server})

    response = post(spec, body)

    assert response.status_code == 204, response.data
    assert seen == {"v": server, "data": server, "validated": server}


# A field whose own ``get_value`` reads another key of the body.


class _ReadsAnotherKey(serializers.CharField):
    def get_value(self, dictionary: Any) -> Any:
        return dictionary.get("v_raw", empty)


class _Raw(serializers.Serializer):
    v = _ReadsAnotherKey(required=False)


def test_a_key_only_a_fields_get_value_reads_is_an_unknown_argument_under_reject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The key is no parameter, so the kernel's closed argument set refuses it
    before the field could read it."""
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", UnknownArguments.REJECT)
    spec = _spec(_reads({}), _Raw, input_data=lambda: {"v": "server"})

    response = post(spec, {"v_raw": "evil"})

    assert response.status_code == 400
    assert response.data["v_raw"][0].code == "unknown"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "the kernel route records no server_values for input_data's answer, so "
        "the field validates what its get_value reads from the body, never the "
        "value input_data put under its name"
    ),
)
def test_a_field_reading_another_key_validates_the_value_put_under_ignore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", UnknownArguments.IGNORE)
    seen: dict[str, Any] = {}
    spec = _spec(_reads(seen), _Raw, input_data=lambda: {"v": "server"})

    response = post(spec, {"v_raw": "evil"})

    assert response.status_code == 204, response.data
    assert seen == {"v": "server", "data": "server", "validated": "server"}


# On a form body drfs wrote the server's value into the form, so the field
# read it as it reads a form: one value for a list a list of one, an empty
# string for an optional field the field left out.


class _Optional(serializers.Serializer):
    v = serializers.CharField(required=False)


class _Nullable(serializers.Serializer):
    v = serializers.CharField(required=False, allow_null=True)


_FORM_READS = {
    "scalar-for-a-list": (_List, "x", ["x"], ["x"]),
    "empty-string": (_Optional, "", "default", None),
    "empty-string-nullable": (_Nullable, "", None, None),
}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "the kernel merges input_data's answer into its checked arguments, a "
        "dict, which the serializer binds, so the server's value is read as a "
        "JSON body's value whatever the client's content type"
    ),
)
@pytest.mark.parametrize(
    ("serializer", "server", "handed", "kept"), _FORM_READS.values(), ids=_FORM_READS.keys()
)
def test_input_data_on_a_form_body_is_read_as_a_form_reads_it(
    serializer: Any, server: Any, handed: Any, kept: Any
) -> None:
    seen: dict[str, Any] = {}
    spec = _spec(_reads(seen), serializer, input_data=lambda: {"v": server})

    response = post(spec, {"v": "evil"}, fmt="multipart")

    assert response.status_code == 204, response.data
    assert seen == {"v": handed, "data": kept, "validated": kept}


# A field whose wire name and ``source`` differ.


class _Sourced(serializers.Serializer):
    tenant = serializers.CharField(source="tenant_id", required=False)


def _with_default(seen: dict[str, Any]) -> Callable[..., None]:
    def service(*, data: Any, tenant: str = "D") -> None:
        seen.update(tenant=tenant, data=data.get("tenant_id"))

    return service


def _without_default(seen: dict[str, Any]) -> Callable[..., None]:
    def service(*, data: Any, tenant: str) -> None:
        seen.update(tenant=tenant, data=data.get("tenant_id"))

    return service


_DEFAULTED = pytest.mark.parametrize(
    "service_for", [_with_default, _without_default], ids=["with-default", "without-default"]
)


@FORMATS
@_DEFAULTED
def test_the_providers_value_by_wire_name_reaches_the_parameter_of_that_name(
    fmt: str, service_for: Callable[..., Any]
) -> None:
    """The author named the parameter, so the provider's ``tenant`` is the
    service's ``tenant``, defaulted or not; the half of drfs' answer the kernel
    route gives (``data`` is the case below)."""
    seen: dict[str, Any] = {}
    spec = _spec(service_for(seen), _Sourced, kwargs=lambda: {"tenant": "srv"})

    response = post(spec, {"tenant": "evil"}, fmt=fmt)

    assert response.status_code == 204, response.data
    assert seen["tenant"] == "srv"


@_KWARGS_GAP
@FORMATS
@_DEFAULTED
def test_the_providers_value_by_wire_name_is_the_fields_value_in_data(
    fmt: str, service_for: Callable[..., Any]
) -> None:
    seen: dict[str, Any] = {}
    spec = _spec(service_for(seen), _Sourced, kwargs=lambda: {"tenant": "srv"})

    response = post(spec, {"tenant": "evil"}, fmt=fmt)

    assert response.status_code == 204, response.data
    assert seen == {"tenant": "srv", "data": "srv"}


@FORMATS
def test_input_data_by_wire_name_leaves_the_parameter_of_that_name_its_default(fmt: str) -> None:
    """``input_data`` is the body's, never an author's naming of a parameter:
    the field validates it under its ``source``."""
    seen: dict[str, Any] = {}
    spec = _spec(_with_default(seen), _Sourced, input_data=lambda: {"tenant": "srv"})

    response = post(spec, {"tenant": "evil"}, fmt=fmt)

    assert response.status_code == 204, response.data
    assert seen == {"tenant": "D", "data": "srv"}
