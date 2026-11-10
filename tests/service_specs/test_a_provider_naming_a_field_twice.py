from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import (
    UNSET,
    DataclassValidator,
    ServiceSpec,
    Unrestricted,
    adispatch,
    dispatch,
)
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


@_CORES
@_DEFAULTS
def test_each_key_reaches_its_own_parameter_off_http(
    run: Callable[..., None], defaults: bool
) -> None:
    seen: dict[str, Any] = {}

    run(_both(seen, defaults=defaults), {"tenant": "evil"})

    assert seen == _HANDED


def _post(spec: ServiceSpec, body: Any, fmt: str) -> Any:
    view = type("_View", (_CreateView,), {"spec": spec}).as_view()
    return view(_factory.post("/", body, format=fmt))


_FMT = pytest.mark.parametrize("fmt", ["json", "multipart"])


@_FMT
@pytest.mark.parametrize(
    "providers",
    [
        {"kwargs": lambda: dict(_BOTH)},
        {"kwargs": lambda: dict(_BOTH), "input_data": lambda: {"tenant": "A"}},
    ],
    ids=["kwargs-alone", "beside-input-data"],
)
def test_a_kwargs_value_named_like_a_field_is_refused(fmt: str, providers: Any) -> None:
    """The wire name is a parameter of the Validator."""
    seen: dict[str, Any] = {}

    with pytest.raises(ImproperlyConfigured, match=r"answered 'tenant'.*ServiceSpec\.input_data"):
        _post(_spec(seen, **providers), {"tenant": "evil"}, fmt)

    assert seen == {}


@_FMT
def test_a_declined_wire_name_is_not_refused(fmt: str) -> None:
    seen: dict[str, Any] = {}

    response = _post(
        _spec(seen, kwargs=lambda: {"tenant": UNSET, "org": "B"}), {"tenant": "c"}, fmt
    )

    assert response.status_code == 204, response.data
    assert seen == {"tenant": "DEFAULT", "org": "B", "data": {"org": "c"}}


@_FMT
def test_a_kwargs_value_named_like_a_source_is_the_service_s(fmt: str) -> None:
    """``org`` is no parameter of the Validator: the provider's value is the service's ``org``."""
    seen: dict[str, Any] = {}
    spec = _spec(
        seen,
        input_data=lambda: {"tenant": "A"},
        kwargs=lambda: {"org": "B"},
    )

    response = _post(spec, {"tenant": "evil"}, fmt)

    assert response.status_code == 204, response.data
    assert seen == {"tenant": "DEFAULT", "org": "B", "data": {"org": "A"}}


def test_a_kwargs_answer_that_is_no_mapping_is_the_kernel_s_to_refuse() -> None:
    with pytest.raises(ImproperlyConfigured, match="ServiceSpec.kwargs returned list"):
        _post(_spec({}, kwargs=lambda: ["tenant"]), {"tenant": "c"}, "json")


@dataclasses.dataclass
class _TenantIn:
    tenant: str = "client"


def test_another_validator_s_kwargs_provider_is_not_checked() -> None:
    """A Validator that is no serializer's declares what it takes itself."""
    seen: dict[str, Any] = {}

    def service(*, data: Any, tenant: str) -> None:
        seen.update(tenant=tenant, data=data)

    spec = ServiceSpec(
        service=service,
        permissions=(Unrestricted(),),
        validator=DataclassValidator(_TenantIn),
        kwargs=lambda: {"tenant": "server"},
        atomic=False,
    )

    response = _post(spec, {"tenant": "evil"}, "json")

    assert response.status_code == 204, response.data
    assert seen == {"tenant": "server", "data": _TenantIn(tenant="evil")}


@_CORES
def test_a_declined_wire_name_leaves_the_parameter_to_its_default(
    run: Callable[..., None],
) -> None:
    """The wire name declined with ``UNSET`` claims none; the source's value is the service's."""
    seen: dict[str, Any] = {}

    run(_spec(seen, kwargs=lambda: {"tenant": UNSET, "org": "B"}), {"tenant": "evil"})

    assert seen == {"tenant": "DEFAULT", "org": "B", "data": {"org": "evil"}}
