"""The Django setting this package reads, read at the call rather than at import."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_LENIENT_JSON_BODY = "SPEC_REST_LENIENT_JSON_BODY"


def lenient_json_body() -> bool:
    """``SPEC_REST_LENIENT_JSON_BODY``: whether a view's serializer alone answers a JSON body.

    ``False`` when the project sets nothing, so a JSON body is checked against the
    spec's declared types first. A view's own ``lenient_json_body`` outranks it.

    Read on every call, never at import, as every setting the kernel reads is: a
    test's ``override_settings`` must reach a view built before it.

    Raises:
        ImproperlyConfigured: anything but a ``bool``, so a ``"false"`` is refused by
            name rather than read as true
            (test_a_setting_that_is_no_bool_is_refused_by_name).
    """
    value: Any = getattr(settings, _LENIENT_JSON_BODY, False)
    if not isinstance(value, bool):
        raise ImproperlyConfigured(
            f"{_LENIENT_JSON_BODY} must be True or False; got {value!r}. It is whether a view's "
            "serializer alone answers a JSON body."
        )
    return value
