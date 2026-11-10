from __future__ import annotations

from tests.conftest_settings import *  # noqa: F403
from tests.conftest_settings import REST_FRAMEWORK as _SUITE_REST_FRAMEWORK

REST_FRAMEWORK = {
    **_SUITE_REST_FRAMEWORK,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
