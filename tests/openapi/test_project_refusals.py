"""The refusals a project configures are the project's to declare, as ``docs/openapi.md`` shows.

The schema documents the 403 and 401 a spec's own checks answer. A view's
``permission_classes`` and its authenticators refuse before the spec is asked,
and a principal who cannot act is refused on an ``Unrestricted`` spec too; the
package documents none of these, and a project declares them with
``@extend_schema(responses=...)``, beside what the spec documents.
"""

from __future__ import annotations

import json
from typing import Any

import jsonschema
import pytest
from django.contrib.auth.models import User
from django.urls import path
from django_service_specs import ServiceSpec, Unrestricted
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.authentication import BasicAuthentication
from rest_framework.permissions import IsAdminUser
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest import ServiceCreateView
from django_spec_rest.openapi import (
    NotAuthenticatedSerializer,
    PermissionDeniedSerializer,
    enable_openapi,
)

_DECLARED = {
    401: OpenApiResponse(NotAuthenticatedSerializer, description="No credentials were sent."),
    403: OpenApiResponse(PermissionDeniedSerializer, description="The caller is not staff."),
}


def _view(responses: dict[int, Any] | None = None) -> type:
    """A staff-only create view over an ``Unrestricted`` spec, behind a challenge."""
    view = type(
        "_View",
        (ServiceCreateView,),
        {
            "spec": ServiceSpec(service=lambda: None, permissions=(Unrestricted(),)),
            "permission_classes": [IsAdminUser],
            "authentication_classes": [BasicAuthentication],
        },
    )
    return view if responses is None else extend_schema(responses=responses)(view)


def _schema() -> tuple[dict[str, Any], Any, Any]:
    enable_openapi()
    undeclared, declared = _view(), _view(_DECLARED)
    schema = SchemaGenerator(
        patterns=[path("undeclared/", undeclared.as_view()), path("declared/", declared.as_view())]
    ).get_schema(request=None, public=True)
    return schema, undeclared.as_view(), declared.as_view()


def test_the_package_documents_none_of_the_view_s_own_refusals() -> None:
    schema, _, _ = _schema()
    assert {"401", "403"}.isdisjoint(schema["paths"]["/undeclared/"]["post"]["responses"])


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("user", "status"),
    [
        (None, 401),
        (lambda: User.objects.create(username="member"), 403),
        (lambda: User.objects.create(username="gone", is_staff=True, is_active=False), 403),
    ],
    ids=["nobody", "not staff", "deactivated"],
)
def test_the_declared_refusals_document_what_the_view_sends(user: Any, status: int) -> None:
    schema, _, view = _schema()
    responses = schema["paths"]["/declared/"]["post"]["responses"]
    # Beside what the spec documents, which the declaration does not drop.
    assert set(responses) == {"201", "204", "401", "403"}
    request = APIRequestFactory().post("/", {}, format="json")
    if user is not None:
        force_authenticate(request, user())
    response = view(request)
    response.render()
    assert response.status_code == status
    documented = responses[str(status)]["content"]["application/json"]["schema"]
    # The package's own components, which the recipe declares.
    component = "NotAuthenticated" if status == 401 else "PermissionDenied"
    assert documented == {"$ref": f"#/components/schemas/{component}"}
    jsonschema.validate(
        json.loads(response.content), {**documented, "components": schema["components"]}
    )
