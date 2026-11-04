"""The suite's settings under the OpenAPI setup the docs give a project.

``tests.conftest_settings`` points DRF's ``DEFAULT_SCHEMA_CLASS`` at
``ServiceAutoSchema``, so every view the suite inspects is on the package's
schema. A project following ``docs/openapi.md`` keeps drf-spectacular's own
``AutoSchema`` there and calls ``enable_openapi()``; the openapi tests of that
setup run under these settings (``tests/openapi/conftest.py``'s
``documented_setup``, and a fresh interpreter by module name).
"""

from __future__ import annotations

from tests.conftest_settings import *  # noqa: F403
from tests.conftest_settings import REST_FRAMEWORK as _SUITE_REST_FRAMEWORK

REST_FRAMEWORK = {
    **_SUITE_REST_FRAMEWORK,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
