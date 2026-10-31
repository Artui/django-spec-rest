"""The server's value for an input field against a client value reaching the same key another way.

On the kernel route ``input_data`` is the seat that fills a
``SerializerValidator`` field: the kernel merges its answer over the caller's
arguments, and the edge puts it onto the body the serializer binds. DRF then
builds ``validated_data`` field by field, so a later field with the same
``source``, a ``source="*"`` nested serializer carrying a key of that name, or
a ``validate()`` copying another field into it puts the client's value back
under the key. The edge records the value the server put, which the Validator
validates on its own and lays back over the key, so the service's parameter,
its ``data`` and the bound serializer's ``validated_data`` all hold the
server's value.

Also: a dotted ``source`` a ``validate()`` replaced is left
as built, a key ``validate()`` renamed is not put back, a dataclass's ``data``
is its instance, a ``many`` spec's rows are handed on as built, and a server
value a field refuses is DRF's 400. A ``to_internal_value`` override reading a
key no field declares meets the kernel's closed argument set first, so under
``REJECT`` it is refused, and under ``IGNORE`` the override reads the client's
value and the server's is laid back over it.

The view's ``get_service_kwargs`` and ``get_input_data`` are the server's
values as ``input_data``'s answer is, and hold through each of the three
second routes.

A typed provider owning a key is ``test_a_typed_provider_owning_a_wire_name``'s.
The query count of validating a related field's server value twice is not
asserted: it is a cost rather than an answer.
The ``kwargs`` provider's value outranking the Validator's for the service's
parameter is ``test_author_values_outrank_the_validator``'s, and its value
named like a field's wire name, refused over HTTP, is
``test_a_kwargs_value_named_like_a_field_is_refused``'s (``tests/service_specs/``).

A ``HiddenField`` takes no input from the server either: ``input_data`` or a
view hook naming one leaves the field its default, and a partial call skips it,
as DRF's loop does, whatever the client sent.

Not asserted here, each for the reason beside it:

- ``input_data`` for a read-only field: it is no parameter, so the case is
  what the kernel makes of an ``input_data`` key no parameter declares;
- every refusal of five server values answered together, and the client's
  refusal answered before the server's value is validated: both are orders of
  the second validation, and the second reads a key no field declares;
- a dotted or flattened field's value reaching the parameter named like the
  field: it is the lay-back this module asserts by its other routes;
- a hook's ``UNSET`` declining a name: a behaviour of the view's hook chain,
  not of a second route, so not this file's.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import ValidationError as DjangoValidationError
from django_service_specs import UnknownArguments
from rest_framework import serializers

from django_spec_rest.dispatch import kernel_edge
from tests.testapp.models import Author
from tests.views.server_value_calls import dispatch_live, open_spec, post
from tests.views.test_kernel_views import _CreateView

pytestmark = pytest.mark.django_db


class _Alias(serializers.Serializer):
    """A second field writing the same ``source``, after the first."""

    tenant = serializers.CharField(required=False)
    alias = serializers.CharField(source="tenant", required=False)


class _InnerTenant(serializers.Serializer):
    tenant = serializers.CharField(required=False)


class _Star(serializers.Serializer):
    """A ``source="*"`` nested serializer whose own ``tenant`` lands at the top level."""

    tenant = serializers.CharField(required=False)
    nested = _InnerTenant(source="*", required=False)


class _Copies(serializers.Serializer):
    """A ``validate()`` copying another field over ``tenant``."""

    tenant = serializers.CharField(required=False)
    other = serializers.CharField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "other" in attrs:
            attrs["tenant"] = attrs["other"]
        return attrs


_SHAPES = {
    "alias": (_Alias, {"tenant": "c1", "alias": "evil"}),
    "star": (_Star, {"tenant": "c1", "nested": {"tenant": "evil"}}),
    "validate": (_Copies, {"other": "evil"}),
}
_SHAPE = pytest.mark.parametrize(("serializer", "body"), _SHAPES.values(), ids=_SHAPES.keys())
# A form body carries a nested object as prefixed keys, which the kernel's flat
# reader does not read, so the ``source="*"`` shape is the JSON body's alone.
_FLAT_SHAPE = pytest.mark.parametrize(
    ("serializer", "body"),
    [_SHAPES["alias"], _SHAPES["validate"]],
    ids=["alias", "validate"],
)
_SERVER = {"tenant": "server", "data": "server", "validated": "server"}


def _server() -> dict[str, Any]:
    return {"tenant": "server"}


def _plain(seen: dict[str, Any]) -> Callable[..., None]:
    def service(*, data: Any, serializer: Any, tenant: str = "default") -> None:
        seen.update(
            tenant=tenant, data=data["tenant"], validated=serializer.validated_data["tenant"]
        )

    return service


@_SHAPE
def test_input_data_outranks_a_second_route_over_http(
    serializer: Any, body: dict[str, Any]
) -> None:
    seen: dict[str, Any] = {}

    response = post(open_spec(_plain(seen), serializer, input_data=_server), body)

    assert response.status_code == 204, response.data
    assert seen == _SERVER


@pytest.mark.parametrize("hook", ["get_service_kwargs", "get_input_data"])
@_SHAPE
def test_a_view_hook_s_value_outranks_a_second_route_over_http(
    hook: str, serializer: Any, body: dict[str, Any]
) -> None:
    """A view hook's value for a field is the server's as ``input_data``'s is:
    the kernel route lays it back over every key, rather than handing the service
    the client's ``"evil"`` through the second route, for its parameter, its
    ``data`` and its ``validated_data`` alike."""
    seen: dict[str, Any] = {}
    hooked = type("_Hooked", (_CreateView,), {hook: lambda self, *_: _server()})

    response = post(open_spec(_plain(seen), serializer), body, view=hooked)

    assert response.status_code == 204, response.data
    assert seen == _SERVER


@_FLAT_SHAPE
def test_input_data_outranks_a_second_route_in_a_form_body(
    serializer: Any, body: dict[str, Any]
) -> None:
    seen: dict[str, Any] = {}

    response = post(open_spec(_plain(seen), serializer, input_data=_server), body, fmt="multipart")

    assert response.status_code == 204, response.data
    assert seen == _SERVER


@_SHAPE
def test_input_data_outranks_a_second_route_through_the_edge(
    serializer: Any, body: dict[str, Any]
) -> None:
    seen: dict[str, Any] = {}

    dispatch_live(open_spec(_plain(seen), serializer, input_data=_server), body)

    assert seen == _SERVER


def _authored() -> dict[str, Any]:
    return {"tenant": "authored"}


def test_a_provider_naming_the_field_input_data_fills_is_refused() -> None:
    """``input_data`` is the seat that fills a field. A ``kwargs`` answer naming
    the same wire name would reach the service unvalidated, so it is refused."""
    seen: dict[str, Any] = {}

    with pytest.raises(ImproperlyConfigured, match="ServiceSpec.input_data"):
        dispatch_live(open_spec(_plain(seen), _Alias, input_data=_server, kwargs=_authored), {})

    assert seen == {}


class _Shouting(_Alias):
    def validate_tenant(self, value: str) -> str:
        return value.upper()


def test_the_value_laid_back_is_the_fields_validate_method_s() -> None:
    """The field's value as ``validated_data`` would have held it: after ``validate_<field>``."""
    seen: dict[str, Any] = {}

    response = post(open_spec(_plain(seen), _Shouting, input_data=_server), {"alias": "evil"})

    assert response.status_code == 204, response.data
    assert seen == {"tenant": "SERVER", "data": "SERVER", "validated": "SERVER"}


class _Lowers(serializers.Serializer):
    tenant = serializers.CharField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "tenant" in attrs:
            attrs["tenant"] = attrs["tenant"].lower()
        return attrs


def test_a_validate_rewrite_of_the_servers_own_value_is_laid_over() -> None:
    """``validate()`` cannot tell the server's value from a client's, and neither
    can the lay-back, so the service sees the value as its field validated it."""
    seen: dict[str, Any] = {}
    spec = open_spec(_plain(seen), _Lowers, input_data=lambda: {"tenant": "SERVER"})

    response = post(spec, {"tenant": "client"})

    assert response.status_code == 204, response.data
    assert seen == {"tenant": "SERVER", "data": "SERVER", "validated": "SERVER"}


class _AuthorIn(serializers.Serializer):
    author = serializers.PrimaryKeyRelatedField(queryset=Author.objects.all(), required=False)
    writer = serializers.PrimaryKeyRelatedField(
        source="author", queryset=Author.objects.all(), required=False
    )


def test_the_value_laid_back_is_the_fields_validated_value() -> None:
    """A primary key the server gives arrives as the row its field resolves it to."""
    mine = Author.objects.create(name="mine")
    theirs = Author.objects.create(name="theirs")
    seen: dict[str, Any] = {}

    def service(*, data: Any, author: Any = None) -> None:
        seen.update(author=author, data=data["author"])

    spec = open_spec(service, _AuthorIn, input_data=lambda: {"author": mine.pk})

    response = post(spec, {"writer": theirs.pk})

    assert response.status_code == 204, response.data
    assert seen == {"author": mine, "data": mine}


class _Dotted(serializers.Serializer):
    """Two fields writing one nested ``source``."""

    tenant = serializers.CharField(source="scope.inner.tenant", required=False)
    alias = serializers.CharField(source="scope.inner.tenant", required=False)


class _DottedFlattened(_Dotted):
    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs["scope"] = attrs["scope"]["inner"]["tenant"]
        return attrs


def _data(seen: dict[str, Any]) -> Callable[..., None]:
    def service(*, data: Any) -> None:
        seen["data"] = data

    return service


def test_a_dotted_source_is_laid_back_where_it_nests() -> None:
    seen: dict[str, Any] = {}

    response = post(open_spec(_data(seen), _Dotted, input_data=_server), {"alias": "evil"})

    assert response.status_code == 204, response.data
    assert seen["data"] == {"scope": {"inner": {"tenant": "server"}}}


def test_a_dotted_source_a_validate_replaced_is_left_as_built() -> None:
    """Where the nesting a dotted ``source`` names is no longer a mapping, ``data`` is as built."""
    seen: dict[str, Any] = {}

    response = post(open_spec(_data(seen), _DottedFlattened, input_data=_server), {"alias": "evil"})

    assert response.status_code == 204, response.data
    assert seen["data"] == {"scope": "evil"}


class _Renames(serializers.Serializer):
    """A ``validate()`` that moves the field's value to a key of its own."""

    tenant = serializers.CharField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "tenant" in attrs:
            attrs["tenant_id"] = attrs.pop("tenant")
        return attrs


def test_a_key_validate_removed_is_not_put_back() -> None:
    """``data`` keeps the serializer's shape, the server's value under the key it was moved to."""
    seen: dict[str, Any] = {}

    def service(*, data: Any) -> None:
        seen["data"] = dict(data)

    dispatch_live(open_spec(service, _Renames, input_data=_server), {"tenant": "c1"})

    assert seen["data"] == {"tenant_id": "server"}


@dataclasses.dataclass
class _TenantInput:
    tenant: str = "unset"


def test_a_dataclass_input_holds_the_servers_value_its_field_validated() -> None:
    """A dataclass instance is the call's ``data`` as built, and its fields the values."""
    seen: dict[str, Any] = {}

    def service(*, data: Any, tenant: str = "default") -> None:
        seen.update(tenant=tenant, data=data.tenant)

    dispatch_live(open_spec(service, _TenantInput, input_data=_server), {"tenant": "c1"})

    assert seen == {"tenant": "server", "data": "server"}


class _Drops(serializers.Serializer):
    tenant = serializers.CharField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs.pop("tenant", None)
        return attrs


def test_a_key_validate_drops_still_reaches_the_parameter() -> None:
    seen: dict[str, Any] = {}

    def service(*, data: Any, tenant: str = "default") -> None:
        seen.update(tenant=tenant, data=dict(data))

    response = post(open_spec(service, _Drops, input_data=_server), {"tenant": "c1"})

    assert response.status_code == 204, response.data
    assert seen == {"tenant": "server", "data": {}}


@pytest.mark.parametrize(
    ("serializer", "row"),
    [(_Alias, {"alias": "evil"}), (_Copies, {"other": "evil"})],
    ids=["alias", "validate"],
)
def test_a_bulk_row_is_handed_on_as_its_serializer_built_it(
    serializer: Any, row: dict[str, Any]
) -> None:
    """A ``many`` spec's rows are handed on as its list serializer built them:
    the server's value for a row's field is not laid back over a second route."""
    seen: dict[str, Any] = {}

    def service(*, data: Any) -> None:
        seen["data"] = [item["tenant"] for item in data]

    dispatch_live(open_spec(service, serializer, many=True, input_data=_server), [row])

    assert seen == {"data": ["evil"]}


# A ``to_internal_value`` override: the serializer's own code, outside DRF's
# field loop, putting the client's value where the server's field reads, or
# building the key without the field. Each reads ``other``, which no field
# declares, so the kernel's closed argument set answers it first.


class _RewritesTheBody(serializers.Serializer):
    """Writes ``other`` over ``tenant`` in the body before the fields read it."""

    tenant = serializers.CharField(required=False)

    def to_internal_value(self, data: Any) -> Any:
        if "other" in data:
            data = {**data, "tenant": data["other"]}
        return super().to_internal_value(data)


class _BuildsTheKey(serializers.Serializer):
    """Builds ``tenant`` from ``other`` without running the field at all."""

    tenant = serializers.CharField(required=False, max_length=6)

    def to_internal_value(self, data: Any) -> Any:
        return {"tenant": data.get("other", data.get("tenant"))}


class _RewritesTheBodyInPlace(serializers.Serializer):
    """Writes ``other`` over ``tenant`` in the body it was given, before the fields read it."""

    tenant = serializers.CharField(required=False)

    def to_internal_value(self, data: Any) -> Any:
        if "other" in data:
            data["tenant"] = data["other"]
        return super().to_internal_value(data)


_OVERRIDES = pytest.mark.parametrize(
    "serializer",
    [_RewritesTheBody, _RewritesTheBodyInPlace, _BuildsTheKey],
    ids=["rewrites-the-body", "rewrites-the-body-in-place", "builds-the-key"],
)


@_OVERRIDES
def test_an_overrides_undeclared_key_is_an_unknown_argument_under_reject(
    monkeypatch: pytest.MonkeyPatch, serializer: Any
) -> None:
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", UnknownArguments.REJECT)
    seen: dict[str, Any] = {}

    response = post(open_spec(_plain(seen), serializer, input_data=_server), {"other": "evil"})

    assert response.status_code == 400
    assert response.data["other"][0].code == "unknown"
    assert seen == {}


@_OVERRIDES
def test_an_overrides_undeclared_key_under_ignore_is_covered_by_the_server_value(
    monkeypatch: pytest.MonkeyPatch, serializer: Any
) -> None:
    """The kernel drops ``other`` from its arguments, but the serializer binds
    the request's body, so the override reads the client's value into
    ``tenant``; the server's value, validated on its own, is laid back over it."""
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", UnknownArguments.IGNORE)
    seen: dict[str, Any] = {}

    dispatch_live(open_spec(_plain(seen), serializer, input_data=_server), {"other": "evil"})

    assert seen == _SERVER


class _Bounded(serializers.Serializer):
    tenant = serializers.CharField(required=False, max_length=6)


_TOO_LONG = {"tenant": ["Ensure this field has no more than 6 characters."]}


def test_a_server_value_its_field_refuses_is_a_400_keyed_by_the_field() -> None:
    seen: dict[str, Any] = {}
    spec = open_spec(_plain(seen), _Bounded, input_data=lambda: {"tenant": "far-too-long"})

    response = post(spec, {})

    assert response.status_code == 400
    assert response.data == _TOO_LONG
    assert response.data["tenant"][0].code == "max_length"
    assert seen == {}


def test_a_server_value_a_field_never_ran_on_is_still_refused_by_it() -> None:
    """``_BuildsTheKey`` never runs its field, so only validating the server's
    value on its own refuses what the field alone refuses."""
    seen: dict[str, Any] = {}
    spec = open_spec(_plain(seen), _BuildsTheKey, input_data=lambda: {"tenant": "far-too-long"})

    response = post(spec, {})

    assert response.status_code == 400
    assert response.data == _TOO_LONG
    assert seen == {}


class _BuildsAndChecks(_BuildsTheKey):
    """``validate_tenant`` refuses with Django's ``ValidationError``, as a model validator would."""

    def validate_tenant(self, value: str) -> str:
        raise DjangoValidationError("Not a tenant of yours.", code="foreign")


def test_a_django_refusal_of_the_server_value_is_a_400_keyed_by_the_field() -> None:
    """``_BuildsAndChecks`` never runs its field, so only the server's value,
    validated on its own, meets ``validate_tenant``: its Django refusal is a
    400 keyed by the field, its code kept, as DRF's own field loop answers one."""
    seen: dict[str, Any] = {}
    spec = open_spec(_plain(seen), _BuildsAndChecks, input_data=_server)

    response = post(spec, {"other": "evil"})

    assert response.status_code == 400
    assert response.data == {"tenant": ["Not a tenant of yours."]}
    assert response.data["tenant"][0].code == "foreign"
    assert seen == {}


class _HiddenTenant(serializers.Serializer):
    tenant = serializers.HiddenField(default="field-default")
    title = serializers.CharField(required=False)


def _hidden(seen: dict[str, Any]) -> Callable[..., None]:
    def service(*, data: Any, serializer: Any) -> None:
        seen.update(data=dict(data), validated=dict(serializer.validated_data))

    return service


@pytest.mark.parametrize("partial", [False, True], ids=["full", "partial"])
@pytest.mark.parametrize("seat", ["input_data", "get_input_data", "get_service_kwargs"])
def test_a_hidden_field_takes_its_default_whatever_the_server_or_the_client_puts(
    seat: str, partial: bool
) -> None:
    """A ``HiddenField`` is the server's own value and takes no input, so neither
    the client's ``"evil"`` nor the server's ``"server"`` reaches it: the field
    takes its default, and a partial call skips it, as DRF's loop does."""
    seen: dict[str, Any] = {}
    fields: dict[str, Any] = {"input_data": _server} if seat == "input_data" else {}
    view = (
        _CreateView
        if seat == "input_data"
        else type("_Hooked", (_CreateView,), {seat: lambda self, *_: _server()})
    )

    response = post(
        open_spec(_hidden(seen), _HiddenTenant, partial=partial, **fields),
        {"tenant": "evil", "title": "t"},
        view=view,
    )

    assert response.status_code == 204, response.data
    held = {"title": "t"} if partial else {"tenant": "field-default", "title": "t"}
    assert seen == {"data": held, "validated": held}
