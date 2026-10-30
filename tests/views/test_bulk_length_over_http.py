"""How long a ``many`` kernel spec's body may be over HTTP.

Changed by design: a drfs live view took a body of any length its list
serializer did not bound, past the kernel's cap. A kernel spec's list is
bounded by its ``many_max_length``, else by ``SERVICE_SPECS_MAX_ARRAY_LENGTH``
(1000 by default), on HTTP as on every transport, so a view taking longer
bodies declares it on the spec. A list serializer's own bound still refuses.
"""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import ServiceSpec, Unrestricted
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView
from django_spec_rest.service_specs.serializer_validator import SerializerValidator

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()
_LONG = [{"title": str(index)} for index in range(1001)]


class _Row(serializers.Serializer):
    title = serializers.CharField()


class _AtMostThree(serializers.ListSerializer):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 3)
        super().__init__(*args, **kwargs)


class _BoundedRow(serializers.Serializer):
    title = serializers.CharField()

    class Meta:
        list_serializer_class = _AtMostThree


def _post(row: Any, body: Any, **seats: Any) -> Any:
    seen: list[int] = []
    spec = ServiceSpec(
        service=lambda *, data: seen.append(len(data)),
        permissions=(Unrestricted(),),
        validator=SerializerValidator(row),
        many=True,
        atomic=False,
        **seats,
    )
    view = type("_View", (ServiceCreateView,), {"spec": spec}).as_view()
    return view(_factory.post("/", body, format="json")), seen


def test_the_kernel_s_cap_holds_on_http() -> None:
    response, seen = _post(_Row, _LONG)
    assert response.status_code == 400
    assert response.data["items"][0].code == "max_length"
    assert seen == []


def test_a_spec_s_many_max_length_lifts_it() -> None:
    response, seen = _post(_Row, _LONG, many_max_length=2000)
    assert response.status_code == 204
    assert seen == [1001]


def test_a_list_serializer_s_own_bound_still_refuses() -> None:
    response, seen = _post(_BoundedRow, [{"title": "a"}] * 4)
    assert response.status_code == 400
    assert response.data["items"]["non_field_errors"][0].code == "max_length"
    assert seen == []
