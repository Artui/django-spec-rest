"""Smoke tests for ``enable_openapi`` import-time and idempotence."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from drf_spectacular.settings import (
    IMPORT_STRINGS,
    SPECTACULAR_DEFAULTS,
    SpectacularSettings,
    spectacular_settings,
)

from django_spec_rest import (
    SelectorListView,
    SelectorRetrieveView,
    SelectorViewSet,
    ServiceCreateView,
    ServiceDeleteView,
    ServiceUpdateView,
    ServiceViewSet,
)
from django_spec_rest.openapi import enable_openapi
from django_spec_rest.openapi.reserved_components_hook import reserved_components_hook

_PROBE = """
import sys

import django

django.setup()

import django_spec_rest
import django_spec_rest.openapi

print(sorted(name for name in sys.modules if name.split(".")[0] == "drf_spectacular"))
"""


def test_importing_the_openapi_package_leaves_drf_spectacular_unimported() -> None:
    """``django_spec_rest.openapi`` is importable without the optional ``drf-spectacular``.

    Only ``enable_openapi()`` loads the schema-generator module, which imports
    it. Run in a fresh interpreter, under the documented setup's settings
    (whose ``DEFAULT_SCHEMA_CLASS`` DRF reads lazily, by name), since this
    process imported ``drf-spectacular`` long ago.
    """
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "tests.documented_settings"},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_enable_openapi_attaches_service_auto_schema_to_views() -> None:
    enable_openapi()
    from django_spec_rest.openapi.service_auto_schema import ServiceAutoSchema

    for view_cls in (
        ServiceCreateView,
        ServiceUpdateView,
        ServiceDeleteView,
        SelectorListView,
        SelectorRetrieveView,
        ServiceViewSet,
        SelectorViewSet,
    ):
        assert isinstance(view_cls.schema, ServiceAutoSchema)


def test_enable_openapi_is_idempotent() -> None:
    enable_openapi()
    enable_openapi()  # second call must not raise


def _projects_hook(result: Any, **kwargs: Any) -> Any:
    return result


def test_the_hook_is_installed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Appended after the project's own hooks, and only once however often it is called.

    Fails without the install's check that the hook is absent.
    """
    monkeypatch.setattr(spectacular_settings, "POSTPROCESSING_HOOKS", [_projects_hook])
    enable_openapi()
    enable_openapi()
    assert [_projects_hook, reserved_components_hook] == spectacular_settings.POSTPROCESSING_HOOKS


def test_a_hook_the_project_lists_is_not_added_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """drf-spectacular imports a dotted path to the very function the install compares."""
    listed = SpectacularSettings(
        user_settings={
            "POSTPROCESSING_HOOKS": [
                "django_spec_rest.openapi.reserved_components_hook.reserved_components_hook"
            ]
        },
        defaults=SPECTACULAR_DEFAULTS,
        import_strings=IMPORT_STRINGS,
    ).POSTPROCESSING_HOOKS
    monkeypatch.setattr(spectacular_settings, "POSTPROCESSING_HOOKS", listed)
    enable_openapi()
    assert [reserved_components_hook] == spectacular_settings.POSTPROCESSING_HOOKS
