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
    """The class a serializer or dataclass declaration renders through."""
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
