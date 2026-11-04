"""Shared internal helpers for the ``openapi`` package.

Loaded only through ``service_auto_schema`` and ``reserved_components_hook``,
which ``enable_openapi`` imports, so importing ``drf-spectacular`` here keeps
it an optional dependency.
"""

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
for _body in (PermissionDeniedSerializer, NotAuthenticatedSerializer):
    set_override(_body, "many", False)

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


class Reserved(NamedTuple):
    """A component name the package keeps, the object it registers under it, and what it documents."""

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
    """Record ``ref``'s string as one the package wrote in the generation ``registry`` belongs to."""
    _PLACED.setdefault(registry, []).append(ref["$ref"])
    return ref


def placed(registry: Any) -> list[str]:
    """The ``$ref`` strings the package wrote in the generation ``registry`` belongs to.

    Read, not taken, so the hook listed twice still finds them the second time.
    """
    return _PLACED.get(registry, [])


class _PlacedComponent(ResolvedComponent):
    """A reserved component of the package's, whose next ``$ref`` is recorded once its class asks.

    drf-spectacular hands every serializer of the component's name the
    component the registry holds, so its ``$ref`` alone cannot say whether
    the package's body or a project's class of the same name asked for it.
    ``_ReservedBodyExtension.get_name`` runs only for the package's own class,
    just before the ``$ref`` is taken, so it arms the component and the
    ``$ref`` it hands out next is recorded as the package's. A project's class
    of the name, which never arms it, gets a ``$ref`` the hook refuses
    (test_a_project_s_serializer_of_the_name_after_is_refused).
    """

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
    """Names the package's own 403 or 401 body by its reserved component, wherever it is resolved.

    drf-spectacular asks a serializer's extension for its component name each
    time it resolves the serializer, on its own ``AutoSchema`` as on
    ``ServiceAutoSchema``, so this is where the package's class is told apart
    from a project's of the same name. The component it registers is a
    ``_PlacedComponent``, armed for the ``$ref`` the resolution takes next
    (test_are_documented_on_drf_spectacular_s_schema_beside_a_package_view). A
    project's object already under the name is refused, since the
    package's body would be documented by it
    (test_a_project_s_serializer_of_the_name_first_is_refused). Only the
    exact class: a project's subclass is its own component. Registered by
    defining a subclass naming the ``target_class``; this one names none, so
    it matches nothing.
    """

    def get_name(self, auto_schema: Any, direction: Any) -> str | None:
        name = get_class(self.target).__name__.removesuffix("Serializer")
        if direction == "request" and spectacular_settings.COMPONENT_SPLIT_REQUEST:
            # Its request twin is ``<name>Request``, a name nobody reserves.
            # Without the direction, test_are_documented_under_split_request_components
            # and test_are_documented_as_a_project_s_response_under_split_request_components
            # fail; without the setting, test_is_documented_as_a_request_body's
            # other case and test_are_documented_nested_in_a_project_s_serializer.
            return None
        if is_patched_serializer(self.target, direction):
            # Its partial twin is ``Patched<name>``, nobody's reserved name
            # either, and drf-spectacular takes no ``$ref`` of ``<name>``, so
            # naming it would leave the component armed for the next class of
            # the name (TestAPatchedRequestOfTheBody).
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
        # Written out rather than read off the serializer: the reading that
        # bypasses this extension is not in every drf-spectacular the floor
        # admits. test_component_descriptions holds it to the class.
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
