"""A refused caller's oversized form answers before Django can report it as suspicious.

``TooManyFieldsSent`` is a ``SuspiciousOperation``. Left to escape, Django's handler answers 400
and logs it to ``django.security.TooManyFieldsSent``, which only happens through that handler,
so these go through the test client rather than calling the view.

A refusal comes first now, so that line is written only for a caller who was admitted: a project
alerting on it no longer hears from anonymous callers sending too many fields.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client, override_settings
from django.urls import path
from django_service_specs import ServiceSpec
from rest_framework import serializers
from rest_framework.authentication import BasicAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request

from django_spec_rest import ServiceCreateView
from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from django_spec_rest.service_specs.serializer_validator import SerializerValidator

SECURITY_LOGGER = "django.security.TooManyFieldsSent"
TOO_MANY_FIELDS = "a=1&b=2"
FORM = "application/x-www-form-urlencoded"


class _Name(serializers.Serializer):
    name = serializers.CharField()


def _reads_the_body(self: Any, request: Request) -> dict[str, Any]:
    return dict(request.data)


def _view(permission: type, **hooks: Any) -> Any:
    attrs = {
        "spec": ServiceSpec(
            service=lambda *, name: None,
            permissions=(DRFPermissionCheck([permission]),),
            validator=SerializerValidator(_Name),
        ),
        "permission_classes": [],
        "authentication_classes": [BasicAuthentication],
        **hooks,
    }
    return type("_View", (ServiceCreateView,), attrs).as_view()


urlpatterns = [
    path("refused/", _view(IsAuthenticated)),
    path("refused-hook/", _view(IsAuthenticated, get_input_data=_reads_the_body)),
    path("admitted/", _view(AllowAny)),
    path("admitted-hook/", _view(AllowAny, get_input_data=_reads_the_body)),
]


def _logged(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.name for record in caplog.records if record.name == SECURITY_LOGGER]


@pytest.mark.urls(__name__)
@override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=1)
@pytest.mark.parametrize("route", ["/refused/", "/refused-hook/"])
def test_a_refused_caller_s_oversized_form_is_not_logged_as_suspicious(
    route: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Whichever read comes first, the edge's own or a view hook's."""
    response = Client().post(route, TOO_MANY_FIELDS, content_type=FORM)
    assert response.status_code == 401
    assert _logged(caplog) == []


@pytest.mark.urls(__name__)
@override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=1)
@pytest.mark.parametrize("route", ["/admitted/", "/admitted-hook/"])
def test_an_admitted_caller_s_oversized_form_is_still_logged_as_suspicious(
    route: str, caplog: pytest.LogCaptureFixture
) -> None:
    """What the refusal changes is who reaches Django's report, never the report itself."""
    response = Client().post(route, TOO_MANY_FIELDS, content_type=FORM)
    assert response.status_code == 400
    assert _logged(caplog) == [SECURITY_LOGGER]
