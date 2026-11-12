from __future__ import annotations

import functools
from dataclasses import is_dataclass
from typing import Any, cast, overload

from rest_framework.serializers import BaseSerializer
from rest_framework_dataclasses.serializers import DataclassSerializer


@overload
def renderable_serializer_class(declared: None) -> None: ...


@overload
def renderable_serializer_class(declared: type) -> type[BaseSerializer[Any]]: ...


def renderable_serializer_class(declared: type | None) -> type[BaseSerializer[Any]] | None:
    """The class a serializer or dataclass declaration renders through.

    A bare dataclass type is wrapped in a ``DataclassSerializer`` — the payload
    the kernel's schema already describes for it, field by field — and anything else comes back
    exactly as declared, ``None`` included. Instantiating the declaration directly
    works for a serializer and fails for a dataclass, whose own ``__init__`` is
    handed ``many=`` / ``context=``; resolving it here first is what lets both
    shapes render.

    Every render site in this package resolves through it: a spec's
    ``SerializerPresenter``, which a view, viewset or action presents through and
    whose ``output()``
    [`audience_projection_for_spec`][django_service_specs.dispatch.audience_projection_for_spec.audience_projection_for_spec]
    reads, so an agent is shaped by the markings of the class it is actually
    rendered with; the OpenAPI schema; and the browsable API's form serializer.
    A transport that instantiates a declaration itself calls this and
    instantiates what it returns:

        serializer_class = renderable_serializer_class(declared)
        payload = serializer_class(
            value, many=many, context=base_serializer_context(view=view, request=request)
        ).data

    A dataclass gets one class for the life of the process, so repeated calls
    return the same object.

    The pass-through is deliberate rather than a check. A ``BaseSerializer``
    subclass is the ordinary case, and a declaration that is neither is refused
    where its schema is derived; refusing it here as well would break a caller
    that renders through a serializer-shaped factory without ever deriving one.
    """
    if isinstance(declared, type) and is_dataclass(declared):
        return _dataclass_serializer_class(declared)
    return cast("type[BaseSerializer[Any]] | None", declared)


# Cached per dataclass type, so every render site and the OpenAPI coercion share one class.
@functools.cache
def _dataclass_serializer_class(dataclass_type: type) -> type[DataclassSerializer[Any]]:
    return type(
        f"_AutoDataclassSerializer_{dataclass_type.__name__}",
        (DataclassSerializer,),
        {"Meta": type("Meta", (), {"dataclass": dataclass_type})},
    )


__all__ = ["renderable_serializer_class"]
