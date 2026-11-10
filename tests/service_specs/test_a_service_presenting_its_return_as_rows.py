from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django_service_specs import ServiceSpec, Unrestricted
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.present import present
from django_service_specs.schema.spec_output_schema import spec_output_schema
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter

pytestmark = pytest.mark.django_db


class _Row(serializers.Serializer):
    title = serializers.CharField()


def _rows() -> list[dict[str, str]]:
    return [{"title": "first"}, {"title": "second"}]


def _listed(**overrides: Any) -> ServiceSpec:
    fields: dict[str, Any] = {
        "service": _rows,
        "permissions": (Unrestricted(),),
        "returns_many": True,
        "presenter": SerializerPresenter(_Row),
    }
    fields.update(overrides)
    return ServiceSpec(**fields)


def test_the_kernel_s_own_dispatch_answers_the_rows() -> None:
    spec = _listed()

    result = dispatch(spec, principal=AnonymousUser(), arguments={})

    assert result.kind == "list"
    assert present(spec, result) == [{"title": "first"}, {"title": "second"}]


def test_the_kernel_s_output_schema_is_an_array_of_the_row() -> None:
    schema = spec_output_schema(_listed())

    assert schema["type"] == "array"
    assert schema["items"]["properties"] == {"title": {"type": "string"}}


class _CreateView(ServiceCreateView):
    permission_classes: Any = []


def test_a_live_view_answers_the_presented_rows() -> None:
    view = type("_View", (_CreateView,), {"spec": _listed()}).as_view()

    response = view(APIRequestFactory().post("/", {}, format="json"))

    assert response.status_code == 201
    assert response.data == [{"title": "first"}, {"title": "second"}]
