"""A component name the package documents a refusal by is refused on a view the package does not document.

``ValidationErrors``, ``PermissionDenied`` and ``NotAuthenticated`` are the
bodies of a spec's 400, 403 and 401. A project's own view on drf-spectacular's
``AutoSchema`` resolving a serializer of one of these names after the package's
refusal is answered the package's component, with drf-spectacular's warning
alone, so its request and response would be documented by the refusal's body.
``reserved_components_hook``, which ``enable_openapi()`` installs, refuses it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import URLPattern, path
from django_service_specs import ServiceSpec, Unrestricted
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import ComponentRegistry, ResolvedComponent
from drf_spectacular.settings import patched_settings, spectacular_settings
from rest_framework import serializers
from rest_framework.authentication import BasicAuthentication
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest import ServiceCreateView
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.openapi.reserved_components_hook import reserved_components_hook
from django_spec_rest.openapi.utils import PermissionDeniedBody
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


_SERIALIZERS = [ValidationErrorsSerializer, PermissionDeniedSerializer, NotAuthenticatedSerializer]


class _Deny(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return False


def _ours(prefix: str) -> URLPattern:
    """A spec documenting all three: a Validator, a DRF check, an authenticator with a challenge.

    Its 201 is the ``Author`` component, a ``$ref`` to a name no one reserves.
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
    return path(f"{prefix}/", view.as_view())


def _ours_refusing_nothing(prefix: str) -> URLPattern:
    """A spec documenting none of the three: no Validator, no check but ``Unrestricted``."""
    spec = ServiceSpec(
        service=lambda: None,
        permissions=(Unrestricted(),),
        presenter=SerializerPresenter(AuthorSerializer),
    )
    view = type("_Ours", (ServiceCreateView,), {"queryset": Author.objects.all(), "spec": spec})
    return path(f"{prefix}/", view.as_view())


def _theirs(prefix: str, serializer: type[serializers.Serializer]) -> URLPattern:
    """A project's own view on drf-spectacular's ``AutoSchema``, posting and answering ``serializer``."""

    class _Theirs(GenericAPIView):
        schema = AutoSchema()
        serializer_class = serializer
        permission_classes = []
        authentication_classes = []

        def post(self, request: Request) -> Response: ...

    return path(f"{prefix}/", _Theirs.as_view())


def _generate(*patterns: URLPattern) -> dict[str, Any]:
    enable_openapi()
    # Not vacuous when this module runs alone: the hook is what is under test.
    assert reserved_components_hook in spectacular_settings.POSTPROCESSING_HOOKS
    return SchemaGenerator(patterns=list(patterns)).get_schema(request=None, public=True)


class TestAReservedName:
    # drf-spectacular walks the paths in order: "a-" resolves before "b-".
    @pytest.mark.parametrize("serializer", _SERIALIZERS, ids=lambda cls: cls.__name__)
    def test_a_reserved_name_is_refused_on_drf_spectacular_s_schema(
        self, serializer: type[serializers.Serializer]
    ) -> None:
        """The package's refusal first: the hook refuses, naming the operation."""
        name = serializer.__name__.removesuffix("Serializer")
        with pytest.raises(ImproperlyConfigured) as raised:
            _generate(_ours("a-ours"), _theirs("b-theirs", serializer))
        message = str(raised.value)
        assert message.startswith(
            f"The operation POST /b-theirs/ is documented as the component {name!r}"
        )
        assert "component_name" in message

    @pytest.mark.parametrize("serializer", _SERIALIZERS, ids=lambda cls: cls.__name__)
    def test_is_refused_when_the_project_s_view_comes_first(
        self, serializer: type[serializers.Serializer]
    ) -> None:
        """The project's serializer first: the package's own schema refuses it, naming the class.

        The registry holds the project's serializer by then, so the package
        meets it while it documents its refusal, before the hook runs.
        """
        with pytest.raises(ImproperlyConfigured, match=serializer.__name__) as raised:
            _generate(_theirs("a-theirs", serializer), _ours("b-ours"))
        assert "component_name" in str(raised.value)

    def test_is_refused_in_a_component_of_the_project_s(self) -> None:
        with pytest.raises(ImproperlyConfigured) as raised:
            _generate(_ours("a-ours"), _theirs("b-theirs", OuterSerializer))
        assert str(raised.value).startswith(
            "The component 'Outer' is documented as the component 'PermissionDenied'"
        )

    def test_is_refused_in_a_webhook(self) -> None:
        registry = ComponentRegistry()
        registry.register_on_missing(
            ResolvedComponent(
                name="PermissionDenied",
                type=ResolvedComponent.SCHEMA,
                object=PermissionDeniedBody,
                schema={},
            )
        )
        result = {
            "webhooks": {
                "refused": {
                    "post": {"requestBody": {"$ref": "#/components/schemas/PermissionDenied"}}
                }
            }
        }
        with pytest.raises(ImproperlyConfigured) as raised:
            reserved_components_hook(
                result=result,
                generator=SimpleNamespace(registry=registry),
                request=None,
                public=True,
            )
        assert str(raised.value).startswith(
            "The webhook 'refused' is documented as the component 'PermissionDenied'"
        )

    def test_the_package_s_own_responses_pass(self) -> None:
        """The package's 400, 403 and 401, and ``ValidationErrors`` nesting itself, are its own.

        Fails without the hook's skip of what the package rendered, or of a
        component's reference to itself.
        """
        schema = _generate(_ours("ours"))
        responses = schema["paths"]["/ours/"]["post"]["responses"]
        assert {"400", "401", "403"} <= set(responses)
        assert {"ValidationErrors", "PermissionDenied", "NotAuthenticated"} <= set(
            schema["components"]["schemas"]
        )

    def test_a_project_s_own_reserved_name_is_documented_without_the_package_s(self) -> None:
        """A name the package registered nothing under in this document is the project's.

        Fails without the hook's ``held_by_package`` filter.
        """
        schema = _generate(
            _ours_refusing_nothing("a-ours"),
            *(_theirs(f"b-theirs-{index}", cls) for index, cls in enumerate(_SERIALIZERS)),
        )
        schemas = schema["components"]["schemas"]
        for serializer in _SERIALIZERS:
            name = serializer.__name__.removesuffix("Serializer")
            assert schemas[name]["properties"] == {"mine": {"type": "string"}}


class TestTheHooksAProjectSets:
    """A list of hooks that replaces drf-spectacular's own, as ``custom_settings`` does, drops the hook."""

    def test_a_list_without_the_hook_loses_the_guard(self) -> None:
        enable_openapi()
        with patched_settings({"POSTPROCESSING_HOOKS": []}):
            schema = SchemaGenerator(
                patterns=[_ours("a-ours"), _theirs("b-theirs", ValidationErrorsSerializer)]
            ).get_schema(request=None, public=True)
        body = schema["paths"]["/b-theirs/"]["post"]["requestBody"]["content"]["application/json"]
        assert body["schema"] == {"$ref": "#/components/schemas/ValidationErrors"}

    def test_a_list_naming_the_hook_keeps_it(self) -> None:
        enable_openapi()
        hook = "django_spec_rest.openapi.reserved_components_hook.reserved_components_hook"
        with (
            patched_settings({"POSTPROCESSING_HOOKS": [hook]}),
            pytest.raises(ImproperlyConfigured, match="POST /b-theirs/"),
        ):
            SchemaGenerator(
                patterns=[_ours("a-ours"), _theirs("b-theirs", ValidationErrorsSerializer)]
            ).get_schema(request=None, public=True)
