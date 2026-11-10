from __future__ import annotations

import inspect
from typing import Any, NamedTuple
from weakref import WeakKeyDictionary

from django.core.exceptions import ImproperlyConfigured
from drf_spectacular.drainage import set_override
from drf_spectacular.extensions import OpenApiSerializerExtension
from drf_spectacular.plumbing import ResolvedComponent, get_class, is_patched_serializer
from drf_spectacular.settings import spectacular_settings
from rest_framework import status as drf_status

from django_spec_rest.openapi.not_authenticated_serializer import NotAuthenticatedSerializer
from django_spec_rest.openapi.permission_denied_serializer import PermissionDeniedSerializer

# One body, never a list: under ENABLE_LIST_MECHANICS_ON_NON_2XX a paginated
# view's 403 or 401 would be wrapped as ``Paginated<Name>List``, and the
# pagination naming asks the extension for a name it takes no ``$ref`` of.
# That override covers the class; an instance with ``many=True`` is a
# ``ListSerializer`` without it, which a list view still pages (as it does a
# project's list), so the pagination naming stops at the list class, named for
# the body, and never asks the extension (TestAListOfTheBody).
for _body in (PermissionDeniedSerializer, NotAuthenticatedSerializer):
    set_override(_body, "many", False)
    set_override(
        _body.Meta.list_serializer_class,
        "component_name",
        _body.__name__.removesuffix("Serializer"),
    )

# Default success status by action / view kind. Mirrors the runtime defaults
# in the standalone views and viewset mixins so the schema lines up with
# what the framework actually returns when the view sets no success status.
_ACTION_DEFAULT_STATUS: dict[str, int] = {
    "create": drf_status.HTTP_201_CREATED,
    "update": drf_status.HTTP_200_OK,
    "partial_update": drf_status.HTTP_200_OK,
    "destroy": drf_status.HTTP_204_NO_CONTENT,
}
_VIEW_CLASS_DEFAULT_STATUS: dict[str, int] = {
    "ServiceCreateView": drf_status.HTTP_201_CREATED,
    "ServiceUpdateView": drf_status.HTTP_200_OK,
    "ServiceDeleteView": drf_status.HTTP_204_NO_CONTENT,
}


def default_status(view: Any) -> int:
    """Pick the HTTP status the runtime would emit when no override is set."""
    action_name = getattr(view, "action", None)
    if isinstance(action_name, str) and action_name in _ACTION_DEFAULT_STATUS:
        return _ACTION_DEFAULT_STATUS[action_name]
    for cls in type(view).__mro__:
        status = _VIEW_CLASS_DEFAULT_STATUS.get(cls.__name__)
        if status is not None:
            return status
    return drf_status.HTTP_200_OK


VALIDATION_ERRORS = "ValidationErrors"


class ValidationErrorsIdentity:
    """The ``ValidationErrors`` component's identity in drf-spectacular's registry."""


class Reserved(NamedTuple):
    """A component name the package keeps, its registered object, and what it documents."""

    owner: type
    body: str


RESERVED_COMPONENTS: dict[str, Reserved] = {
    VALIDATION_ERRORS: Reserved(ValidationErrorsIdentity, "the body of a Validator's refusal"),
    "PermissionDenied": Reserved(
        PermissionDeniedSerializer, "the body of a refused permission check"
    ),
    "NotAuthenticated": Reserved(
        NotAuthenticatedSerializer, "the body of a caller nobody authenticated"
    ),
}
"""Every component name the package documents its own body under, and refuses a project's."""


def is_a(candidate: Any, owner: type) -> bool:
    """Whether ``candidate``, a class or an instance, is ``owner``'s."""
    return candidate is owner or isinstance(candidate, owner)


def held_by_package(registry: Any, name: str) -> bool:
    """Whether ``registry`` holds the package's own object under the reserved ``name``."""
    owner = RESERVED_COMPONENTS[name].owner
    try:
        held = registry[ResolvedComponent(name=name, type=ResolvedComponent.SCHEMA, object=owner)]
    except KeyError:
        return False
    return is_a(held.object, owner)


def name_taken(where: str, name: str) -> ImproperlyConfigured:
    """The refusal for a component of the project's own under a name the package reserves."""
    return ImproperlyConfigured(
        f"{where} is documented as the component {name!r}, the name django_spec_rest "
        f"gives {RESERVED_COMPONENTS[name].body}. Name the serializer's component "
        "another way, with @extend_schema_serializer(component_name=...)."
    )


def serializer_named(holder: Any) -> str:
    """A serializer class or instance, by its dotted name."""
    owner = holder if isinstance(holder, type) else type(holder)
    return f"{owner.__module__}.{owner.__qualname__}"


_PLACED: WeakKeyDictionary[Any, list[str]] = WeakKeyDictionary()
"""The ``$ref`` strings the package wrote to a reserved name, by the generation's registry.

Keyed by the registry because a view's schema is shared between generations,
and between threads, while each generation has a registry of its own; held
weakly, so a generation that never reaches the hook leaves nothing behind.
The string object, not the ``{"$ref": ...}`` around it, is what is kept:
drf-spectacular copies the mapping of a ``$ref`` it adds a field's
``readOnly`` or ``nullable`` to, and keeps the string
(test_are_documented_nested_in_a_project_s_serializer).
"""


def place(registry: Any, ref: dict[str, Any]) -> dict[str, Any]:
    """Record ``ref``'s string as one the package wrote, in the generation's ``registry``."""
    _PLACED.setdefault(registry, []).append(ref["$ref"])
    return ref


def placed(registry: Any) -> list[str]:
    """The ``$ref`` strings the package wrote in the generation ``registry`` belongs to."""
    return _PLACED.get(registry, [])


class _PlacedComponent(ResolvedComponent):
    """A package-reserved component, whose next ``$ref`` is recorded once its class asks."""

    registry: Any = None
    armed = False

    @property
    def ref(self) -> dict[str, Any]:
        # A fresh string each time, never a constant a project could hold.
        ref = {"$ref": f"#/components/{self.type}/{self.name}"}
        if not self.armed:
            return ref
        self.armed = False
        return place(self.registry, ref)


class _ReservedBodyExtension(OpenApiSerializerExtension):
    """Names the package's own 403 or 401 body by its reserved component wherever resolved."""

    def get_name(self, auto_schema: Any, direction: Any) -> str | None:
        name = get_class(self.target).__name__.removesuffix("Serializer")
        if direction == "request" and spectacular_settings.COMPONENT_SPLIT_REQUEST:
            # Its request twin is ``<name>Request``, a name nobody reserves.
            return None
        if is_patched_serializer(self.target, direction):
            return None
        registry = auto_schema.registry
        key = ResolvedComponent(name=name, type=ResolvedComponent.SCHEMA, object=self.target)
        try:
            held = registry[key]
        except KeyError:
            held = _PlacedComponent(
                name=name,
                type=ResolvedComponent.SCHEMA,
                object=self.target,
                schema=self.map_serializer(auto_schema, direction),
            )
            held.registry = registry
            registry.register(held)
        if not isinstance(held, _PlacedComponent):
            raise name_taken(serializer_named(held.object), name)
        held.armed = True
        return name

    def map_serializer(self, auto_schema: Any, direction: Any) -> dict[str, Any]:
        # Written out, not read off the serializer: older drf-spectacular lacks that path.
        return {
            "type": "object",
            "description": inspect.cleandoc(get_class(self.target).__doc__ or ""),
            "properties": {"detail": {"type": "string"}},
            "required": ["detail"],
        }


class _PermissionDeniedExtension(_ReservedBodyExtension):
    target_class = PermissionDeniedSerializer


class _NotAuthenticatedExtension(_ReservedBodyExtension):
    target_class = NotAuthenticatedSerializer
