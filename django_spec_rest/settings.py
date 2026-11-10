from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_LENIENT_JSON_BODY = "SPEC_REST_LENIENT_JSON_BODY"


def lenient_json_body() -> bool:
    """``SPEC_REST_LENIENT_JSON_BODY``: whether a view's serializer alone answers a JSON body."""
    value: Any = getattr(settings, _LENIENT_JSON_BODY, False)
    if not isinstance(value, bool):
        raise ImproperlyConfigured(
            f"{_LENIENT_JSON_BODY} must be True or False; got {value!r}. It is whether a view's "
            "serializer alone answers a JSON body."
        )
    return value
