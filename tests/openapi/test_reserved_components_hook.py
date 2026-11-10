from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.urls import URLPattern
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.hooks import postprocess_schema_enums
from drf_spectacular.plumbing import ComponentRegistry, ResolvedComponent
from drf_spectacular.settings import patched_settings, spectacular_settings

from django_spec_rest.openapi import PermissionDeniedSerializer, enable_openapi
from django_spec_rest.openapi.reserved_components_hook import reserved_components_hook
from tests.openapi.reserved_names import (
    SERIALIZERS,
    ValidationErrorsSerializer,
    ours,
    ours_refusing_nothing,
    theirs,
)


def _generate(*patterns: URLPattern) -> dict[str, Any]:
    enable_openapi()
    # Not vacuous when this module runs alone: the hook is what is under test.
    assert reserved_components_hook in spectacular_settings.POSTPROCESSING_HOOKS
    return SchemaGenerator(patterns=list(patterns)).get_schema(request=None, public=True)


class TestTheHook:
    def test_is_refused_in_a_webhook(self) -> None:
        registry = ComponentRegistry()
        registry.register_on_missing(
            ResolvedComponent(
                name="PermissionDenied",
                type=ResolvedComponent.SCHEMA,
                object=PermissionDeniedSerializer,
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
        """The package's 400, 403 and 401, and ``ValidationErrors`` nesting itself, are its own."""
        schema = _generate(ours("ours"))
        responses = schema["paths"]["/ours/"]["post"]["responses"]
        assert {"400", "401", "403"} <= set(responses)
        assert {"ValidationErrors", "PermissionDenied", "NotAuthenticated"} <= set(
            schema["components"]["schemas"]
        )

    def test_a_project_s_own_reserved_name_is_documented_without_the_package_s(self) -> None:
        """A name the package registered nothing under in this document is the project's."""
        schema = _generate(
            ours_refusing_nothing("a-ours"),
            *(theirs(f"b-theirs-{index}", cls) for index, cls in enumerate(SERIALIZERS)),
        )
        schemas = schema["components"]["schemas"]
        for serializer in SERIALIZERS:
            name = serializer.__name__.removesuffix("Serializer")
            assert schemas[name]["properties"] == {"mine": {"type": "string"}}


class TestARawReferenceOnAPackageView:
    """A ``$ref`` to a reserved name the project writes itself is the project's, on any view."""

    def test_a_raw_reserved_reference_on_a_package_view_is_refused(self) -> None:
        """A package view declaring ``{"$ref": ".../PermissionDenied"}`` over its 403 is refused."""
        enable_openapi()
        reference = {"$ref": "#/components/schemas/PermissionDenied"}
        with pytest.raises(ImproperlyConfigured) as raised:
            _generate(ours("a-ours"), ours("b-declared", responses={403: reference}))
        assert str(raised.value).startswith(
            "The operation POST /b-declared/ is documented as the component 'PermissionDenied'"
        )


def _deep_copying_hook(result: Any, **kwargs: Any) -> Any:
    return copy.deepcopy(result)


def _json_roundtrip_hook(result: Any, **kwargs: Any) -> Any:
    return json.loads(json.dumps(result))


def _shallow_rebuild_hook(result: Any, **kwargs: Any) -> Any:
    for operations in result["paths"].values():
        for operation in operations.values():
            for response in operation.get("responses", {}).values():
                for media in response.get("content", {}).values():
                    media["schema"] = dict(media["schema"])
    return result


class TestAProjectHookThatCopiesTheSchema:
    """The hook knows the package's references by identity, so it must see them before rebuilds."""

    @pytest.mark.parametrize(
        "copying_hook", [_deep_copying_hook, _json_roundtrip_hook, _shallow_rebuild_hook]
    )
    def test_a_copying_hook_of_the_project_runs_after_it(
        self, copying_hook: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A clash-free document still generates."""
        monkeypatch.setattr(
            spectacular_settings, "POSTPROCESSING_HOOKS", [postprocess_schema_enums, copying_hook]
        )
        schema = _generate(ours("ours"))
        assert {"400", "401", "403"} <= set(schema["paths"]["/ours/"]["post"]["responses"])


class TestTheHooksAProjectSets:
    """A hook list replacing drf-spectacular's own, as ``custom_settings`` does, drops the hook."""

    def test_a_list_without_the_hook_loses_the_guard(self) -> None:
        enable_openapi()
        with patched_settings({"POSTPROCESSING_HOOKS": []}):
            schema = SchemaGenerator(
                patterns=[ours("a-ours"), theirs("b-theirs", ValidationErrorsSerializer)]
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
                patterns=[ours("a-ours"), theirs("b-theirs", ValidationErrorsSerializer)]
            ).get_schema(request=None, public=True)
