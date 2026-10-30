"""A ``request`` or ``view`` key a client sends, which no field or parameter declares.

The kernel seeds ``request`` and ``view`` from the call's context, so a client
sending either names no argument of the spec. The edge strips nothing before it
calls the kernel's ``dispatch``: under ``REJECT`` the key is refused as
"Unknown argument.", a 400 naming it, as on every other transport; under
``IGNORE`` it is dropped unseen, and a callable declaring ``request`` is handed
the view's own. drfs dropped a caller's ``request`` under either policy and
refused only ``view``; that answer changes by design.

Which policy HTTP runs under is an open question, decided by one line,
``UNKNOWN_ARGUMENTS`` in ``dispatch/kernel_edge.py``, so each test sets it and
asserts both answers.
"""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from django_service_specs.types.unknown_arguments import UnknownArguments
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorRetrieveView, ServiceCreateView
from django_spec_rest.dispatch import kernel_edge
from django_spec_rest.service_specs.serializer_validator import SerializerValidator

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_POLICIES = pytest.mark.parametrize(
    "policy",
    [UnknownArguments.REJECT, UnknownArguments.IGNORE],
    ids=["reject", "ignore"],
    indirect=True,
)


@pytest.fixture
def policy(request: Any, monkeypatch: pytest.MonkeyPatch) -> UnknownArguments:
    chosen: UnknownArguments = request.param
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", chosen)
    return chosen


class _TitleIn(serializers.Serializer):
    title = serializers.CharField()


class _RetrieveView(SelectorRetrieveView):
    """Renders through DRF's ``serializer_class``, which a kernel spec does not reach."""

    class _Echo(serializers.Serializer):
        def to_representation(self, instance: Any) -> Any:
            return instance

    serializer_class = _Echo


def _post(spec: ServiceSpec, body: Any) -> Response:
    view = type("_View", (ServiceCreateView,), {"spec": spec}).as_view()
    return view(factory.post("/", body, format="json"))


def _refused(response: Response, key: str) -> None:
    assert response.status_code == 400, response.data
    assert "Unknown argument." in str(response.data[key])


@_POLICIES
@pytest.mark.parametrize("key", ["request", "view"])
def test_a_body_key_no_field_declares(policy: UnknownArguments, key: str) -> None:
    received: dict[str, Any] = {}

    def service(*, data: Any, request: Any, view: Any) -> None:
        received.update(data=dict(data), request=request, view=view)

    spec = ServiceSpec(service=service, permissions=_OPEN, validator=SerializerValidator(_TitleIn))

    response = _post(spec, {"title": "t", key: "spoofed"})

    if policy is UnknownArguments.REJECT:
        _refused(response, key)
        assert received == {}
    else:
        assert response.status_code == 204, response.data
        assert received["data"] == {"title": "t"}
        assert isinstance(received["request"], Request)
        assert isinstance(received["view"], ServiceCreateView)


@_POLICIES
def test_a_body_key_a_spec_with_no_validator_does_not_declare(policy: UnknownArguments) -> None:
    received: list[Any] = []
    spec = ServiceSpec(service=lambda *, request: received.append(request), permissions=_OPEN)

    response = _post(spec, {"request": "spoofed"})

    if policy is UnknownArguments.REJECT:
        _refused(response, "request")
        assert received == []
    else:
        assert response.status_code == 204, response.data
        (request,) = received
        assert isinstance(request, Request)


@_POLICIES
def test_a_query_key_a_selector_does_not_declare(policy: UnknownArguments) -> None:
    spec = SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk, request: {"pk": pk, "request": type(request).__name__},
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
        permissions=_OPEN,
    )
    view = type("_View", (_RetrieveView,), {"spec": spec}).as_view()

    response = view(factory.get("/", {"request": "spoofed"}), pk="1")

    if policy is UnknownArguments.REJECT:
        _refused(response, "request")
    else:
        assert response.status_code == 200, response.data
        assert response.data == {"pk": 1, "request": "Request"}


@_POLICIES
def test_a_row_key_no_field_declares(policy: UnknownArguments) -> None:
    received: list[Any] = []

    def service(*, data: Any, request: Any) -> None:
        received.append(([dict(row) for row in data], request))

    spec = ServiceSpec(
        service=service, permissions=_OPEN, many=True, validator=SerializerValidator(_TitleIn)
    )

    response = _post(spec, [{"title": "a", "request": "spoofed"}])

    if policy is UnknownArguments.REJECT:
        # Keyed by the row, under the spec's ``many_argument``, as the kernel
        # refuses each row.
        assert response.status_code == 400, response.data
        assert "Unknown argument." in str(response.data["items"][0]["request"])
        assert received == []
    else:
        assert response.status_code == 204, response.data
        ((rows, request),) = received
        assert rows == [{"title": "a"}]
        assert isinstance(request, Request)
