from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import UnknownArguments
from rest_framework import serializers
from rest_framework.fields import empty

from django_spec_rest.dispatch import kernel_edge
from tests.views.server_value_calls import FORMATS, dispatch_live, open_spec, post
from tests.views.test_kernel_views import _CreateView

pytestmark = pytest.mark.django_db


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
    """The server's owner is the one validated, handed on in ``data``."""
    alice = User.objects.create(username="alice")
    bob = User.objects.create(username="bob")
    seen: dict[str, Any] = {}
    spec = open_spec(_owned(seen), _OwnedIn, input_data=_owner)

    response = post(spec, {"title": "t", "user": bob.pk}, fmt=fmt, user=alice)

    assert response.status_code == 204, response.data
    assert seen == {"data": alice, "validated": alice, "user": alice}
    assert [alice] == _VALIDATED


def test_input_data_for_a_field_named_user_outranks_the_clients_through_the_edge() -> None:
    alice = User.objects.create(username="alice")
    bob = User.objects.create(username="bob")
    seen: dict[str, Any] = {}

    dispatch_live(
        open_spec(_owned(seen), _OwnedIn, input_data=_owner),
        {"title": "t", "user": bob.pk},
        user=alice,
    )

    assert seen == {"data": alice, "validated": alice, "user": alice}
    assert [alice] == _VALIDATED


@FORMATS
def test_the_clients_value_for_a_field_named_user_stays_the_fields_with_no_input_data(
    fmt: str,
) -> None:
    """Nothing the server put, so the field validates the client's value; the seed keeps its own."""
    alice = User.objects.create(username="alice")
    bob = User.objects.create(username="bob")
    seen: dict[str, Any] = {}

    response = post(
        open_spec(_owned(seen), _OwnedIn), {"title": "t", "user": bob.pk}, fmt=fmt, user=alice
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
    spec = open_spec(_reads(seen), serializer, input_data=lambda: {"v": server})

    response = post(spec, body)

    assert response.status_code == 204, response.data
    assert seen == {"v": server, "data": server, "validated": server}


@_READ
def test_input_data_is_the_value_put_however_the_field_reads_a_json_body_through_the_edge(
    serializer: Any, server: Any, form: dict[str, Any], body: dict[str, Any]
) -> None:
    seen: dict[str, Any] = {}

    dispatch_live(open_spec(_reads(seen), serializer, input_data=lambda: {"v": server}), body)

    assert seen == {"v": server, "data": server, "validated": server}


# A form body carries a nested or a list field as DRF's prefixed keys -
# ``v.tenant``, ``v[0]tenant``, ``v[0]`` - which are DRF's spelling of the
# declared field ``v``. The edge reads them as the field does, so to the kernel
# they are the field's value, under either policy, and the server's value is
# the field's.


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
    spec = open_spec(_reads(seen), serializer, input_data=lambda: {"v": server})

    response = post(spec, form, fmt="multipart")

    assert response.status_code == 204, response.data
    assert seen == {"v": server, "data": server, "validated": server}


def test_a_spelling_its_field_does_not_read_is_an_unknown_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A nested serializer reads ``v.tenant`` and never ``v[0]``."""
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", UnknownArguments.REJECT)
    seen: dict[str, Any] = {}

    response = post(open_spec(_reads(seen), _Nested), {"v[0]": "evil"}, fmt="multipart")

    assert response.status_code == 400
    assert response.data["v[0]"][0].code == "unknown"
    assert seen == {}


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
    spec = open_spec(_reads(seen), serializer, input_data=lambda: {"v": server})

    response = post(spec, form, fmt="multipart")

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
    """The key is no parameter, so the kernel's closed argument set refuses it."""
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", UnknownArguments.REJECT)
    spec = open_spec(_reads({}), _Raw, input_data=lambda: {"v": "server"})

    response = post(spec, {"v_raw": "evil"})

    assert response.status_code == 400
    assert response.data["v_raw"][0].code == "unknown"


def test_a_field_reading_another_key_validates_the_value_put_under_ignore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", UnknownArguments.IGNORE)
    seen: dict[str, Any] = {}
    spec = open_spec(_reads(seen), _Raw, input_data=lambda: {"v": "server"})

    response = post(spec, {"v_raw": "evil"})

    assert response.status_code == 204, response.data
    assert seen == {"v": "server", "data": "server", "validated": "server"}


# The kernel route binds ``input_data``'s value as the author returned it, so a server value means
# the same whatever the client's content type, and one its field refuses is
# DRF's 400 keyed by the field, as
# test_a_server_value_its_field_refuses_is_a_400_keyed_by_the_field holds on
# a JSON body.


class _Optional(serializers.Serializer):
    v = serializers.CharField(required=False)


class _Nullable(serializers.Serializer):
    v = serializers.CharField(required=False, allow_null=True)


_NOT_A_LIST = {"v": ['Expected a list of items but got type "str".']}
_BLANK = {"v": ["This field may not be blank."]}
_FORM_READS = {
    "scalar-for-a-list": (_List, "x", _NOT_A_LIST, "not_a_list"),
    "empty-string": (_Optional, "", _BLANK, "blank"),
    "empty-string-nullable": (_Nullable, "", _BLANK, "blank"),
}


@pytest.mark.parametrize(
    ("serializer", "server", "refusal", "code"), _FORM_READS.values(), ids=_FORM_READS.keys()
)
def test_input_data_on_a_form_body_is_taken_as_the_author_returned_it(
    serializer: Any, server: Any, refusal: dict[str, Any], code: str
) -> None:
    seen: dict[str, Any] = {}
    spec = open_spec(_reads(seen), serializer, input_data=lambda: {"v": server})

    response = post(spec, {"v": "evil"}, fmt="multipart")

    assert response.status_code == 400
    assert response.data == refusal
    assert response.data["v"][0].code == code
    assert seen == {}


# A field whose wire name and ``source`` differ.


class _Sourced(serializers.Serializer):
    tenant = serializers.CharField(source="tenant_id", required=False)


def _with_default(seen: dict[str, Any]) -> Callable[..., None]:
    def service(*, data: Any, tenant: str = "D") -> None:
        seen.update(tenant=tenant, data=data.get("tenant_id"))

    return service


@FORMATS
def test_the_providers_value_by_wire_name_is_refused(fmt: str) -> None:
    """The wire name is a parameter of the Validator."""
    seen: dict[str, Any] = {}
    spec = open_spec(_with_default(seen), _Sourced, kwargs=lambda: {"tenant": "srv"})

    with pytest.raises(ImproperlyConfigured, match="ServiceSpec.input_data"):
        post(spec, {"tenant": "evil"}, fmt=fmt)

    assert seen == {}


@FORMATS
def test_a_get_service_kwargs_value_by_wire_name_reaches_the_parameter_of_that_name(
    fmt: str,
) -> None:
    """A ``get_service_kwargs`` key naming a field by its wire name names that parameter too."""
    seen: dict[str, Any] = {}
    hooked = type("_Hooked", (_CreateView,), {"get_service_kwargs": lambda self: {"tenant": "srv"}})

    response = post(
        open_spec(_with_default(seen), _Sourced), {"tenant": "evil"}, fmt=fmt, view=hooked
    )

    assert response.status_code == 204, response.data
    assert seen == {"tenant": "srv", "data": "srv"}


@FORMATS
def test_input_data_by_wire_name_leaves_the_parameter_of_that_name_its_default(fmt: str) -> None:
    """``input_data`` is the body's, never an author's naming of a parameter."""
    seen: dict[str, Any] = {}
    spec = open_spec(_with_default(seen), _Sourced, input_data=lambda: {"tenant": "srv"})

    response = post(spec, {"tenant": "evil"}, fmt=fmt)

    assert response.status_code == 204, response.data
    assert seen == {"tenant": "D", "data": "srv"}


class _ReadOnlyWithADefault(serializers.Serializer):
    """A read-only field with a default, whose key a ``validate()`` drops."""

    ro = serializers.CharField(read_only=True, default="field-default")
    title = serializers.CharField()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs.pop("ro", None)
        return attrs


def test_input_data_for_a_read_only_field_with_a_default_holds_no_server_value() -> None:
    """A read-only field takes no value in DRF's loop."""
    seen: dict[str, Any] = {}

    def service(*, data: Any, ro: str = "parameter-default") -> None:
        seen.update(data=dict(data), ro=ro)

    hooked = type("_Hooked", (_CreateView,), {"get_input_data": lambda self, *_: {"ro": "srv"}})

    response = post(open_spec(service, _ReadOnlyWithADefault), {"title": "t"}, view=hooked)

    assert response.status_code == 204, response.data
    assert seen == {"data": {"title": "t"}, "ro": "parameter-default"}


class _DottedTenant(serializers.Serializer):
    tenant = serializers.CharField(source="org.name", required=False)


def test_a_dotted_fields_server_value_reaches_the_parameter_named_like_the_field() -> None:
    """A dotted ``source`` has no key of its own in ``data``."""
    seen: dict[str, Any] = {}

    def service(*, data: Any, tenant: str = "D-tenant", org: Any = "D-org") -> None:
        seen.update(data=dict(data), tenant=tenant, org=org)

    hooked = type("_Hooked", (_CreateView,), {"get_input_data": lambda self, *_: {"tenant": "srv"}})

    response = post(open_spec(service, _DottedTenant), {"tenant": "evil"}, view=hooked)

    assert response.status_code == 204, response.data
    assert seen == {"data": {"org": {"name": "srv"}}, "tenant": "srv", "org": {"name": "srv"}}
