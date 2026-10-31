"""``kernel_input_serializer_class`` - the serializer a form for a kernel service spec's body renders with."""

from __future__ import annotations

from functools import cache
from typing import Any

from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from rest_framework.fields import empty
from rest_framework.serializers import BaseSerializer, Serializer

from django_spec_rest.service_specs.renderable_serializer_class import renderable_serializer_class
from django_spec_rest.service_specs.serializer_validator import SerializerValidator


def kernel_input_serializer_class(spec: KernelServiceSpec) -> type[BaseSerializer[Any]]:
    """The class ``get_serializer_class()`` answers for a kernel service spec on a route with none.

    DRF's browsable renderer builds a form for each write method through the
    view's ``get_serializer()``, outside any ``try``, on every page it renders
    (an OPTIONS answer, a GET, a 405), while a spec-only kernel route declares
    no ``serializer_class`` and DRF's own resolution ends in its assertion. The
    body the spec accepts is the one to offer: its ``SerializerValidator``'s
    serializer, a bare dataclass wrapped as it is for rendering, or a
    serializer of no fields where the spec declares no such Validator, which
    the renderer draws as an empty form.

    The form is never bound to a row. For PUT and PATCH DRF passes the
    instance the page presented, and a spec's input need not be that row's
    shape: an input field the model lacks ended the page in an
    ``AttributeError`` (test_spec_options'
    test_a_get_rendered_as_html_on_a_kernel_detail_route_renders_its_forms).

    Only the form reads it. A kernel spec's own call validates through its
    Validator and presents through its presenter, never through
    ``get_serializer()``.
    """
    # One arc to coverage: a SerializerValidator by test_spec_options'
    # create-view row, and a spec declaring none by its
    # create-view-with-no-validator row.
    if isinstance(spec.validator, SerializerValidator):
        return _unbound(renderable_serializer_class(spec.validator.serializer))
    return _unbound(Serializer)


def standalone_form_serializer_class(view: Any) -> type[BaseSerializer[Any]] | None:
    """The answer a standalone create or update view gives, or ``None`` to resolve as DRF does.

    Asked by ``ServiceCreateView`` and ``ServiceUpdateView`` themselves rather
    than by ``MutationFlowMixin``, which every service viewset also carries
    ahead of ``ActionSerializerResolver``: an override there would take the
    resolver's own answer away from the viewset. A delete view draws no write
    form, so it never asks.

    The two conditions are one arc to coverage; the missing ``serializer_class``
    is held by the create-view row of
    test_a_kernel_views_own_serializer_class_draws_its_forms.
    """
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
