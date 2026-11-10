"""Routes and serializers for the tests of the component names the package keeps.

A spec documenting the package's 400, 403 and 401 on one side; on the other, a
project's own view on drf-spectacular's ``AutoSchema`` posting and answering a
serializer named like one of them.
"""

from __future__ import annotations

from typing import Any

from django.urls import URLPattern, path
from django_service_specs import ServiceSpec, Unrestricted
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.authentication import BasicAuthentication
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest import ServiceCreateView
from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer


class ValidationErrorsSerializer(serializers.Serializer):
    mine = serializers.CharField()


class PermissionDeniedSerializer(serializers.Serializer):
    mine = serializers.CharField()


class NotAuthenticatedSerializer(serializers.Serializer):
    mine = serializers.CharField()


class OuterSerializer(serializers.Serializer):
    refusal = PermissionDeniedSerializer()


SERIALIZERS = [ValidationErrorsSerializer, PermissionDeniedSerializer, NotAuthenticatedSerializer]


class _Deny(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return False


def ours(prefix: str, responses: Any = None) -> URLPattern:
    """A spec documenting all three: a Validator, a DRF check, an authenticator with a challenge.

    Its 201 is the ``Author`` component, a ``$ref`` to a name no one reserves.
    ``responses``, given, is the project's ``@extend_schema(responses=...)`` on
    the view, laid over what the spec documents; ``enable_openapi()`` must run
    first, since ``extend_schema`` subclasses the schema the view has.
    """
    spec = ServiceSpec(
        service=lambda: None,
        permissions=(DRFPermissionCheck([_Deny]),),
        validator=SerializerValidator(AuthorSerializer),
        presenter=SerializerPresenter(AuthorSerializer),
    )
    view = type(
        "_Ours",
        (ServiceCreateView,),
        {
            "queryset": Author.objects.all(),
            "spec": spec,
            "permission_classes": [],
            "authentication_classes": [BasicAuthentication],
        },
    )
    if responses is not None:
        view = extend_schema(responses=responses)(view)
    return path(f"{prefix}/", view.as_view())


def ours_refusing_nothing(prefix: str) -> URLPattern:
    """A spec documenting none of the three: no Validator, no check but ``Unrestricted``."""
    spec = ServiceSpec(
        service=lambda: None,
        permissions=(Unrestricted(),),
        presenter=SerializerPresenter(AuthorSerializer),
    )
    view = type("_Ours", (ServiceCreateView,), {"queryset": Author.objects.all(), "spec": spec})
    return path(f"{prefix}/", view.as_view())


def theirs(prefix: str, serializer: type[serializers.Serializer]) -> URLPattern:
    """A project view on drf-spectacular's ``AutoSchema``, posting and answering ``serializer``."""

    class _Theirs(GenericAPIView):
        schema = AutoSchema()
        serializer_class = serializer
        permission_classes = []
        authentication_classes = []

        def post(self, request: Request) -> Response: ...

    return path(f"{prefix}/", _Theirs.as_view())
