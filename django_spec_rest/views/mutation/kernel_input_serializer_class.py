from __future__ import annotations

from functools import cache
from typing import Any

from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from rest_framework.fields import empty
from rest_framework.serializers import BaseSerializer, Serializer

from django_spec_rest.service_specs.renderable_serializer_class import renderable_serializer_class
from django_spec_rest.service_specs.serializer_validator import SerializerValidator


def kernel_input_serializer_class(spec: KernelServiceSpec) -> type[BaseSerializer[Any]]:
    """The class ``get_serializer_class()`` answers for a kernel spec on a route with none."""
    if isinstance(spec.validator, SerializerValidator):
        return _unbound(renderable_serializer_class(spec.validator.serializer))
    return _unbound(Serializer)


def standalone_form_serializer_class(view: Any) -> type[BaseSerializer[Any]] | None:
    """The answer a standalone create or update view gives, or ``None`` to resolve as DRF does."""
    spec = getattr(view, "spec", None)
    if isinstance(spec, KernelServiceSpec) and getattr(view, "serializer_class", None) is None:
        return kernel_input_serializer_class(spec)
    return None


@cache
def _unbound(serializer_class: type[BaseSerializer[Any]]) -> type[BaseSerializer[Any]]:
    """``serializer_class``, dropping whatever instance it is constructed with."""

    class Unbound(serializer_class):  # ty: ignore[unsupported-base]
        def __init__(self, instance: Any = None, data: Any = empty, **kwargs: Any) -> None:
            super().__init__(None, data, **kwargs)

    Unbound.__name__ = Unbound.__qualname__ = serializer_class.__name__
    return Unbound
