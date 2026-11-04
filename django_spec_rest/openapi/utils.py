"""Shared internal helpers for the ``openapi`` package.

Loaded only through ``service_auto_schema`` and ``reserved_components_hook``,
which ``enable_openapi`` imports, so importing ``drf-spectacular`` here keeps
it an optional dependency.
"""

from __future__ import annotations

from typing import Any, NamedTuple
from weakref import WeakKeyDictionary

from django.core.exceptions import ImproperlyConfigured
from drf_spectacular.plumbing import ResolvedComponent
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import status as drf_status
from rest_framework.serializers import CharField, Serializer

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
    """Pick the HTTP status the runtime would emit when no override is set.

    Looks at ``view.action`` first (viewset path), then the view class name
    (standalone view path). Falls back to ``200 OK`` for ``@service_action``
    and any unrecognised surface, mirroring the decorator's own default.
    """
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
    """The ``ValidationErrors`` component's identity in drf-spectacular's registry.

    The registry tells components apart by the class handed as their
    ``object``. ``ComponentIdentity`` would say this too, but it is new in
    drf-spectacular 0.28 and the floor is 0.27.
    """


@extend_schema_serializer(component_name="PermissionDenied")
class PermissionDeniedBody(Serializer):
    """The caller may not run this operation. Why is under `detail`."""

    # The docstring is the component's description, so it is a client's.
    detail = CharField()


@extend_schema_serializer(component_name="NotAuthenticated")
class NotAuthenticatedBody(Serializer):
    """No caller was authenticated. Why is under `detail`."""

    # The docstring is the component's description, so it is a client's.
    detail = CharField()


class Reserved(NamedTuple):
    """A component name the package keeps, the object it registers under it, and what it documents."""

    owner: type
    body: str


RESERVED_COMPONENTS: dict[str, Reserved] = {
    VALIDATION_ERRORS: Reserved(ValidationErrorsIdentity, "the body of a Validator's refusal"),
    "PermissionDenied": Reserved(PermissionDeniedBody, "the body of a refused permission check"),
    "NotAuthenticated": Reserved(NotAuthenticatedBody, "the body of a caller nobody authenticated"),
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
    """The refusal for a component of the project's own under a name the package reserves.

    drf-spectacular only warns of two components of one name and then keeps one
    for both, so the project's response, or the package's body, would be
    documented by the other's.
    """
    return ImproperlyConfigured(
        f"{where} is documented as the component {name!r}, the name django_spec_rest "
        f"gives {RESERVED_COMPONENTS[name].body}. Name the serializer's component "
        "another way, with @extend_schema_serializer(component_name=...)."
    )


def serializer_named(holder: Any) -> str:
    """A serializer class or instance, by its dotted name."""
    owner = holder if isinstance(holder, type) else type(holder)
    return f"{owner.__module__}.{owner.__qualname__}"


_PLACED: WeakKeyDictionary[Any, list[Any]] = WeakKeyDictionary()
"""The schemas the package rendered with a reserved ``$ref``, by the generation's registry.

Keyed by the registry because a view's schema is shared between generations,
and between threads, while each generation has a registry of its own; held
weakly, so a generation that never reaches the hook leaves nothing behind.
"""


def place(registry: Any, schema: Any) -> None:
    """Record ``schema`` as one the package rendered in the generation ``registry`` belongs to."""
    _PLACED.setdefault(registry, []).append(schema)


def placed(registry: Any) -> list[Any]:
    """The schemas the package rendered in the generation ``registry`` belongs to.

    Read, not taken, so the hook listed twice still finds them the second time.
    """
    return _PLACED.get(registry, [])
