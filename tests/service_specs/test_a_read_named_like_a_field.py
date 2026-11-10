from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import Parameter, Parameters, ServiceSpec, Unrestricted
from rest_framework import serializers

from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.views.test_kernel_views import _CreateView

_TWO_SOURCES = "declared by two sources"


class _TitleIn(serializers.Serializer):
    title = serializers.CharField()


class _SourcedIn(serializers.Serializer):
    heading = serializers.CharField(source="title")


def _spec(serializer: type[serializers.Serializer], read: str) -> ServiceSpec:
    return ServiceSpec(
        service=lambda **_: None,
        permissions=(Unrestricted(),),
        validator=SerializerValidator(serializer),
        reads=Parameters.of(Parameter(read, "string")),
    )


def test_a_read_named_like_a_field_is_refused_when_the_parameters_are_assembled() -> None:
    spec = _spec(_TitleIn, "title")

    with pytest.raises(ImproperlyConfigured, match=_TWO_SOURCES):
        spec.parameters()


def test_a_read_named_like_a_field_s_source_is_no_collision() -> None:
    """The parameter is the wire name, so a read named like the ``source`` is a second argument."""
    spec = _spec(_SourcedIn, "title")

    assert spec.parameters().names() == frozenset({"heading", "title"})


def test_a_view_refuses_the_collision_at_as_view() -> None:
    view = type("_View", (_CreateView,), {"spec": _spec(_TitleIn, "title")})

    with pytest.raises(ImproperlyConfigured, match=_TWO_SOURCES):
        view.as_view()
