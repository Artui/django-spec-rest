"""A provider naming one field by both its wire name and its ``source``.

A serializer field ``tenant = CharField(source="org")`` validates the wire
name's value into ``data`` under ``org``, and the Validator's values are keyed
by the source too, so a service's ``org`` parameter is handed that value and
its ``tenant`` parameter nothing. A spec whose providers name both keys gets
each to the parameter of its name, neither dropped for the other, through the
kernel's two seats: ``input_data``'s ``tenant`` is the field's, validated into
``data`` over what the client sent, and ``kwargs``' ``tenant`` and ``org`` are
the service's own, outranking what the Validator returns.

drfs read both from one view hook, whose value named like a field was the
serializer's as well, over what the body sent. A kernel spec's ``kwargs`` seat
feeds the callable alone, on every transport, so a ``kwargs`` value named like
a field never reaches the serializer, and the field validates what the client
sent. No decision of the carry-over list names that answer, so
test_a_kwargs_value_named_like_a_field_is_the_service_s_alone records drfs'
answer as an expected failure pending the owner's decision.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth.models import AnonymousUser
from django_service_specs import UNSET, ServiceSpec, Unrestricted, adispatch, dispatch
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.views.test_kernel_views import _CreateView

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()


class _SourcedIn(serializers.Serializer):
    title = serializers.CharField(required=False)
    tenant = serializers.CharField(source="org", required=False)


def _service(seen: dict[str, Any], *, defaults: bool) -> Callable[..., None]:
    if defaults:

        def with_defaults(*, data: Any, tenant: str = "DEFAULT", org: str = "DEFAULT") -> None:
            seen.update(tenant=tenant, org=org, data=dict(data))

        return with_defaults

    def required(*, data: Any, tenant: str, org: str) -> None:
        seen.update(tenant=tenant, org=org, data=dict(data))

    return required


def _spec(seen: dict[str, Any], *, defaults: bool = True, **providers: Any) -> ServiceSpec:
    return ServiceSpec(
        service=_service(seen, defaults=defaults),
        permissions=(Unrestricted(),),
        validator=SerializerValidator(_SourcedIn),
        atomic=False,
        **providers,
    )


def _sync(spec: ServiceSpec, arguments: dict[str, Any]) -> None:
    dispatch(spec, principal=AnonymousUser(), arguments=arguments)


def _async(spec: ServiceSpec, arguments: dict[str, Any]) -> None:
    async_to_sync(adispatch)(spec, principal=AnonymousUser(), arguments=arguments)


_CORES = pytest.mark.parametrize("run", [_sync, _async], ids=["sync", "async"])
_DEFAULTS = pytest.mark.parametrize("defaults", [True, False], ids=["defaults", "required"])
_BOTH = {"tenant": "A", "org": "B"}
_HANDED = {"tenant": "A", "org": "B", "data": {"org": "A"}}


def _both(seen: dict[str, Any], *, defaults: bool) -> ServiceSpec:
    return _spec(
        seen,
        defaults=defaults,
        input_data=lambda: {"tenant": "A"},
        kwargs=lambda: dict(_BOTH),
    )


@_DEFAULTS
@pytest.mark.parametrize("fmt", ["json", "multipart"])
def test_each_key_reaches_its_own_parameter_over_http(defaults: bool, fmt: str) -> None:
    seen: dict[str, Any] = {}
    view = type("_View", (_CreateView,), {"spec": _both(seen, defaults=defaults)}).as_view()

    response = view(_factory.post("/", {"tenant": "evil"}, format=fmt))

    assert response.status_code == 204, response.data
    assert seen == _HANDED


@_CORES
@_DEFAULTS
def test_each_key_reaches_its_own_parameter_off_http(
    run: Callable[..., None], defaults: bool
) -> None:
    seen: dict[str, Any] = {}

    run(_both(seen, defaults=defaults), {"tenant": "evil"})

    assert seen == _HANDED


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "open owner decision: a kernel spec's kwargs feed the callable only, "
        "where drfs fed the field"
    ),
)
@pytest.mark.parametrize("fmt", ["json", "multipart"])
def test_a_kwargs_value_named_like_a_field_is_the_service_s_alone(fmt: str) -> None:
    """Records drfs' answer pending the decision: the provider's value is the field's too.

    drfs' hook value was the field's as well, over the body's, so ``data``
    carried the provider's ``A``. The kernel's ``kwargs`` seat never feeds the
    Validator, so ``data`` carries what the body sent (``evil``) while the
    service's ``tenant`` is the provider's.
    """
    seen: dict[str, Any] = {}
    spec = _spec(seen, kwargs=lambda: dict(_BOTH))
    view = type("_View", (_CreateView,), {"spec": spec}).as_view()

    response = view(_factory.post("/", {"tenant": "evil"}, format=fmt))

    assert response.status_code == 204, response.data
    assert seen == _HANDED


@_CORES
def test_a_declined_wire_name_leaves_the_parameter_to_its_default(
    run: Callable[..., None],
) -> None:
    """The wire name declined with ``UNSET`` claims nothing, and the source's value is the service's."""
    seen: dict[str, Any] = {}

    run(_spec(seen, kwargs=lambda: {"tenant": UNSET, "org": "B"}), {"tenant": "evil"})

    assert seen == {"tenant": "DEFAULT", "org": "B", "data": {"org": "evil"}}
