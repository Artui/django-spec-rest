"""The ``PermissionDenied`` and ``NotAuthenticated`` components are this schema's, and no serializer may take their names.

drf-spectacular strips ``Serializer`` from a class's name, so a project's
``PermissionDeniedSerializer`` is the component ``PermissionDenied`` too, and
would re-point every spec 403 ``$ref`` at its own fields (or the 403 would
document the project's response by ``detail``). The handling is the
``ValidationErrors`` component's (``test_validation_errors_component_name``):
refused with ``ImproperlyConfigured``, whichever of the two registers first,
so each order is driven for each name.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import URLPattern, path
from django_service_specs import ServiceSpec, Unrestricted
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers
from rest_framework.authentication import BasicAuthentication
from rest_framework.permissions import BasePermission

from django_spec_rest import ServiceCreateView
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Author


class PermissionDeniedSerializer(serializers.Serializer):
    mine = serializers.CharField()


class NotAuthenticatedSerializer(serializers.Serializer):
    mine = serializers.CharField()


@extend_schema_serializer(component_name="RenamedDenied")
class _RenamedDenied(PermissionDeniedSerializer): ...


@extend_schema_serializer(component_name="RenamedUnauthenticated")
class _RenamedUnauthenticated(NotAuthenticatedSerializer): ...


class _Deny(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return False


def _route(prefix: str, *, checks: tuple[Any, ...], presenter: Any) -> URLPattern:
    spec = ServiceSpec(
        service=lambda: None, permissions=checks, presenter=SerializerPresenter(presenter)
    )
    view = type(
        "_View",
        (ServiceCreateView,),
        {
            "queryset": Author.objects.all(),
            "spec": spec,
            "permission_classes": [],
            "authentication_classes": [BasicAuthentication],
        },
    )
    return path(f"{prefix}/", view.as_view())


def _refusing(prefix: str) -> URLPattern:
    """Documents both the 403 and the 401: a DRF check behind an authenticator with a challenge."""
    return _route(prefix, checks=(DRFPermissionCheck([_Deny]),), presenter=serializers.Serializer)


def _named(prefix: str, presenter: Any) -> URLPattern:
    return _route(prefix, checks=(Unrestricted(),), presenter=presenter)


def _generate(*patterns: URLPattern) -> dict[str, Any]:
    enable_openapi()
    return SchemaGenerator(patterns=list(patterns)).get_schema(request=None, public=True)


_SERIALIZERS = [PermissionDeniedSerializer, NotAuthenticatedSerializer]


class TestASerializerTakingAComponentName:
    # drf-spectacular walks the paths in order: "a-" resolves before "b-".
    @pytest.mark.parametrize("serializer", _SERIALIZERS, ids=lambda cls: cls.__name__)
    def test_is_refused_when_the_serializer_comes_first(self, serializer: type) -> None:
        with pytest.raises(ImproperlyConfigured, match=serializer.__name__) as raised:
            _generate(_named("a-theirs", serializer), _refusing("b-ours"))
        assert "component_name" in str(raised.value)

    @pytest.mark.parametrize("serializer", _SERIALIZERS, ids=lambda cls: cls.__name__)
    def test_is_refused_when_the_refusal_comes_first(self, serializer: type) -> None:
        with pytest.raises(ImproperlyConfigured, match=serializer.__name__) as raised:
            _generate(_refusing("a-ours"), _named("b-theirs", serializer))
        assert "component_name" in str(raised.value)

    def test_is_documented_once_it_is_named_another_way(self) -> None:
        schema = _generate(
            _named("a-denied", _RenamedDenied),
            _named("b-unauthenticated", _RenamedUnauthenticated),
            _refusing("c-ours"),
        )
        schemas = schema["components"]["schemas"]
        assert schemas["RenamedDenied"]["properties"] == {"mine": {"type": "string"}}
        assert schemas["RenamedUnauthenticated"]["properties"] == {"mine": {"type": "string"}}
        assert list(schemas["PermissionDenied"]["properties"]) == ["detail"]
        assert list(schemas["NotAuthenticated"]["properties"]) == ["detail"]

    def test_the_refusals_alone_are_unaffected(self) -> None:
        schemas = _generate(_refusing("ours"))["components"]["schemas"]
        assert list(schemas["PermissionDenied"]["properties"]) == ["detail"]
        assert list(schemas["NotAuthenticated"]["properties"]) == ["detail"]
