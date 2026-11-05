"""Every component the package registers is described for a client, not for this package's reader.

drf-spectacular gives a serializer's component its class docstring as the
``description`` (the first one up the MRO), so a docstring written for the API
reference would publish mkdocs cross-reference syntax and the package's private
names in every generated document.
"""

from __future__ import annotations

import re
from typing import Any, TypedDict

from django.urls import URLPattern, path
from django_service_specs import ServiceSpec
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.authentication import BasicAuthentication
from rest_framework.permissions import AllowAny

from django_spec_rest import ServiceCreateView
from django_spec_rest.openapi import (
    SERVICE_ERROR_METADATA_KEY,
    ActionUnavailableSerializer,
    ServiceConflictSerializer,
    ServiceNotFoundSerializer,
    ServiceValidationErrorSerializer,
    enable_openapi,
)
from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author

_CROSS_REFERENCE = re.compile(r"\]\[")
"""mkdocs-autorefs' ``[text][identifier]``."""

_PRIVATE_NAME = re.compile(r"(?<![\w.])_[A-Za-z]\w*")
"""A name with a leading underscore, such as ``_ServiceAPIException``."""


class TaskSerializer(serializers.Serializer):
    """A task, by its title."""

    title = serializers.CharField()
    owner = serializers.CharField()


class _Owned(TypedDict):
    owner: str


def _owner() -> _Owned:
    return {"owner": "me"}


def _view(responses: dict[int, Any] | None = None) -> type:
    """A create view documenting every component a spec does: a 400, a 401, a 403 and a 422.

    Its body is ``TaskLessOwner``, derived from ``TaskSerializer``, since ``input_data``
    fills ``owner``.
    """
    spec = ServiceSpec(
        service=lambda **_: None,
        permissions=(DRFPermissionCheck([AllowAny]),),
        validator=SerializerValidator(TaskSerializer),
        presenter=SerializerPresenter(TaskSerializer),
        input_data=_owner,
        metadata={SERVICE_ERROR_METADATA_KEY: True},
    )
    view = type(
        "_View",
        (ServiceCreateView,),
        {
            "queryset": Author.objects.all(),
            "spec": spec,
            "authentication_classes": [BasicAuthentication],
        },
    )
    return view if responses is None else extend_schema(responses=responses)(view)


def _registered() -> dict[str, dict[str, Any]]:
    """The components of a generated document that this package registered, by name.

    Each component whose object is a class of the package's, and the body
    derived from a project's serializer, which drf-spectacular's serializer
    metaclass places in its own module.
    """
    enable_openapi()
    patterns: list[URLPattern] = [
        path("spec/", _view().as_view()),
        path(
            "refusals/",
            _view(
                {
                    400: ServiceValidationErrorSerializer,
                    404: ServiceNotFoundSerializer,
                    409: ActionUnavailableSerializer,
                }
            ).as_view(),
        ),
        path("conflict/", _view({409: ServiceConflictSerializer}).as_view()),
    ]
    generator = SchemaGenerator(patterns=patterns)
    schema = generator.get_schema(request=None, public=True)
    names = {
        component.name
        for component in generator.registry._components.values()
        if (
            component.object if isinstance(component.object, type) else type(component.object)
        ).__module__.startswith("django_spec_rest.")
    }
    return {name: schema["components"]["schemas"][name] for name in names | {"TaskLessOwner"}}


def test_no_component_the_package_registers_describes_itself_to_its_reader() -> None:
    registered = _registered()
    # Sized so every kind is read: the spec's refusals, the exported
    # serializers, and a body derived from the author's serializer.
    assert set(registered) == {
        "ActionUnavailable",
        "NotAuthenticated",
        "PermissionDenied",
        "ServiceConflict",
        "ServiceError",
        "ServiceNotFound",
        "ServiceValidationError",
        "TaskLessOwner",
        "ValidationErrors",
    }
    leaks = {
        name: component["description"]
        for name, component in registered.items()
        if _CROSS_REFERENCE.search(component.get("description", ""))
        or _PRIVATE_NAME.search(component.get("description", ""))
    }
    assert leaks == {}


def test_a_derived_body_keeps_the_author_s_description() -> None:
    assert _registered()["TaskLessOwner"]["description"] == "A task, by its title."
