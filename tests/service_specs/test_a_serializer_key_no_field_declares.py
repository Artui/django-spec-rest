"""A caller's ``serializer`` key no field declares is an unknown argument; a field of that name is the serializer's.

The kernel route strips nothing: the key reaches the kernel's
closed argument set, which refuses it as "Unknown argument." under
``UnknownArguments.REJECT`` and drops it under ``IGNORE``, as every other
transport answers. That is a change by design, and each test asserts both
policies' answers, so the policy ``UNKNOWN_ARGUMENTS`` sets for the HTTP edge
can change without a test changing.

A serializer was always free to declare a field named ``serializer``, and it
still is: ``SerializerValidator`` leaves such a field out of its parameters,
the edge hands the body's value to the serializer, and it validates into
``data`` under either policy while the service's ``serializer`` stays the
bound one. Off HTTP the kernel's own ``dispatch`` has nowhere to put that
value, which is why ``unsendable`` names the field when it is required.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django_service_specs import (
    InvalidArguments,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    UnknownArguments,
    Unrestricted,
    dispatch,
)
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorListView
from django_spec_rest.dispatch import kernel_edge
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.views.test_kernel_views import _CreateView

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_UNKNOWN = ["Unknown argument."]


@pytest.fixture(params=[UnknownArguments.REJECT, UnknownArguments.IGNORE], ids=["reject", "ignore"])
def policy(request: Any, monkeypatch: pytest.MonkeyPatch) -> UnknownArguments:
    """The HTTP edge's policy, set to each answer in turn."""
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", request.param)
    return request.param


class _TitleIn(serializers.Serializer):
    title = serializers.CharField()


class _SerializerFieldIn(serializers.Serializer):
    serializer = serializers.CharField()
    title = serializers.CharField()


def _post(spec: ServiceSpec, body: Any) -> Response:
    view = type("_View", (_CreateView,), {"spec": spec}).as_view()
    return view(_factory.post("/", body, format="json"))


def _messages(detail: Any) -> list[str]:
    return [str(message) for message in detail]


def test_a_selector_callers_serializer_key_is_unknown(policy: UnknownArguments) -> None:
    seen: list[Any] = []

    def titles(*, title: str) -> list[Any]:
        seen.append(title)
        return []

    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=titles,
        # Required, since the mount check refuses an optional read over a keyword with no default.
        reads=Parameters.of(Parameter("title", "string", required=True)),
        permissions=_OPEN,
    )
    view = type("_View", (SelectorListView,), {"spec": spec, "serializer_class": _TitleIn})

    response = view.as_view()(_factory.get("/?title=t&serializer=spoofed"))

    if policy is UnknownArguments.REJECT:
        assert response.status_code == 400
        # The whole body: the key is the wire name the caller sent, and nothing else is refused.
        assert response.data == {"serializer": _UNKNOWN}
        assert seen == []
    else:
        assert response.status_code == 200, response.data
        assert seen == ["t"]


@pytest.mark.parametrize("validated", [True, False], ids=["validated", "no-validator"])
def test_a_service_callers_serializer_key_is_unknown(
    policy: UnknownArguments, validated: bool
) -> None:
    seen: list[Any] = []
    if validated:
        spec = ServiceSpec(
            service=lambda *, data: seen.append(dict(data)),
            permissions=_OPEN,
            validator=SerializerValidator(_TitleIn),
            atomic=False,
        )
        body: dict[str, Any] = {"title": "t"}
    else:
        spec = ServiceSpec(service=lambda: seen.append({}), permissions=_OPEN, atomic=False)
        body = {}

    response = _post(spec, {**body, "serializer": "spoofed"})

    if policy is UnknownArguments.REJECT:
        assert response.status_code == 400
        assert _messages(response.data["serializer"]) == _UNKNOWN
        assert seen == []
    else:
        assert response.status_code == 204, response.data
        assert seen == [body]


def test_a_rows_serializer_key_is_unknown(policy: UnknownArguments) -> None:
    """A ``many`` spec's rows are the kernel's as sent, so the key is a row's unknown argument."""
    seen: list[Any] = []
    spec = ServiceSpec(
        service=lambda *, data: seen.extend(dict(row) for row in data),
        permissions=_OPEN,
        validator=SerializerValidator(_TitleIn),
        many=True,
        atomic=False,
    )

    response = _post(spec, [{"title": "a", "serializer": "spoofed"}])

    if policy is UnknownArguments.REJECT:
        assert response.status_code == 400
        assert _messages(response.data["items"][0]["serializer"]) == _UNKNOWN
        assert seen == []
    else:
        assert response.status_code == 204, response.data
        assert seen == [{"title": "a"}]


def _sees_the_bound_serializer(seen: dict[str, Any]) -> ServiceSpec:
    def service(*, data: Any, serializer: Any) -> None:
        seen.update(data=dict(data), serializer=type(serializer).__name__)

    return ServiceSpec(
        service=service,
        permissions=_OPEN,
        validator=SerializerValidator(_SerializerFieldIn),
        atomic=False,
    )


def test_an_input_field_named_serializer_validates_into_data(policy: UnknownArguments) -> None:
    seen: dict[str, Any] = {}

    response = _post(_sees_the_bound_serializer(seen), {"title": "t", "serializer": "sent"})

    assert response.status_code == 204, response.data
    assert seen == {
        "data": {"serializer": "sent", "title": "t"},
        "serializer": "_SerializerFieldIn",
    }


def test_an_input_field_named_serializer_is_required_in_the_serializers_words(
    policy: UnknownArguments,
) -> None:
    seen: dict[str, Any] = {}

    response = _post(_sees_the_bound_serializer(seen), {"title": "t"})

    assert response.status_code == 400
    assert response.data == {"serializer": ["This field is required."]}
    assert seen == {}


@pytest.mark.parametrize(
    ("unknown", "expected"),
    [
        (UnknownArguments.REJECT, {"serializer": _UNKNOWN}),
        (UnknownArguments.IGNORE, {"serializer": ["This field is required."]}),
    ],
    ids=["reject", "ignore"],
)
def test_off_http_the_field_cannot_be_sent(
    unknown: UnknownArguments, expected: dict[str, list[str]]
) -> None:
    """The kernel's own ``dispatch`` hands a Validator only its parameters, and
    the field is none: refused as unknown, or dropped and then missing."""
    spec = _sees_the_bound_serializer({})

    with pytest.raises(InvalidArguments) as excinfo:
        dispatch(
            spec,
            principal=AnonymousUser(),
            arguments={"title": "t", "serializer": "sent"},
            unknown_arguments=unknown,
        )

    assert {key: _messages(value) for key, value in excinfo.value.detail.items()} == expected
    validator = spec.validator
    assert isinstance(validator, SerializerValidator)
    assert validator.unsendable == frozenset({"serializer"})
