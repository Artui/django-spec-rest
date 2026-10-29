"""``GET`` detail endpoint backed by a selector spec or DRF lookup."""

from __future__ import annotations

from typing import Any, ClassVar

from django_service_specs.dispatch.present import present
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from rest_framework.generics import GenericAPIView
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from django_spec_rest.dispatch.renderable_serializer_class import renderable_serializer_class
from django_spec_rest.selectors.utils import dispatch_kernel_selector, dispatch_selector_for_spec
from django_spec_rest.types.selector_kind import SelectorKind
from django_spec_rest.types.selector_spec import SelectorSpec
from django_spec_rest.views.spec_validation import validate_selector_view_spec
from django_spec_rest.views.utils import (
    _JsonNullResponse,
    add_affordances,
    get_class_attr,
    layer_serializer_context,
)


class SelectorRetrieveView(RetrieveModelMixin, GenericAPIView):
    """``GET`` endpoint that returns a single object.

    Set ``spec`` to a
    [`SelectorSpec`][django_spec_rest.types.selector_spec.SelectorSpec] to
    configure the selector and/or the output serializer. Both fields are optional:

    - ``spec.selector`` overrides ``get_object()``; ``None`` falls back to
      ``self.get_object()`` — standard DRF lookup using ``queryset`` and
      ``lookup_field``. Returning ``None`` or raising ``Model.DoesNotExist``
      results in a 404 — or, when the spec sets ``allow_none=True``, a
      ``200`` with a JSON ``null`` body (the nullable-resource contract;
      the output serializer is skipped).
    - ``spec.output_serializer`` overrides ``get_serializer_class()``; ``None``
      falls back to DRF's standard ``serializer_class`` attribute.

    ``spec = None`` (the default) keeps both as vanilla DRF.

    A kernel ``SelectorSpec`` on ``spec`` runs through the kernel's own
    ``dispatch`` and is presented by its own ``presenter``, with the affordance
    answers it declares; ``None`` under its ``allow_none`` is a ``200`` with a
    JSON ``null`` body, presented by nothing. A kernel spec declaring neither
    presenter nor affordances is rendered by the view's ``serializer_class``.
    """

    spec: ClassVar[SelectorSpec | None] = None

    @classmethod
    def as_view(cls, **initkwargs: Any) -> Any:
        validate_selector_view_spec(cls, expected_kind=SelectorKind.RETRIEVE)
        return super().as_view(**initkwargs)

    def get_selector_kwargs(self) -> dict[str, Any]:
        return {}

    def get_permissions(self) -> list[Any]:
        s: SelectorSpec | None = get_class_attr(self, "spec")
        if isinstance(s, SelectorSpec) and s.permission_classes is not None:
            return [permission() for permission in s.permission_classes]
        return list(super().get_permissions())

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        s: SelectorSpec | None = get_class_attr(self, "spec")
        if isinstance(s, SelectorSpec) and s.output_serializer is not None:
            return renderable_serializer_class(s.output_serializer)
        return super().get_serializer_class()

    def get_serializer_context(self) -> dict[str, Any]:
        base: dict[str, Any] = dict(super().get_serializer_context())
        s: SelectorSpec | None = get_class_attr(self, "spec")
        if not isinstance(s, SelectorSpec) or s.output_serializer_context is None:
            return base
        return layer_serializer_context(
            base,
            self,
            self.request,
            direction_hook=None,
            action_hook=None,
            spec_provider=s.output_serializer_context,
            extras={"instance": getattr(self, "_resolved_instance", None)},
        )

    def get_object(self) -> Any:
        """Resolve the target row through ``spec.selector``, if one is set.

        **``filter_backends`` do not apply here.** DRF runs
        ``filter_queryset()`` inside its own ``get_object()``, so overriding
        that method — this view, or any hand-written override — drops them.
        A tenant-scoping backend in ``DEFAULT_FILTER_BACKENDS`` scopes a
        sibling list view and not this lookup. Scope the selector's own
        queryset, or declare the rule as ``SelectorSpec.filter_set``, which
        the dispatcher applies on both the list and the retrieve path.
        """
        s: SelectorSpec | None = get_class_attr(self, "spec")
        if s is None or s.selector is None:
            obj = super().get_object()
        else:
            obj = dispatch_selector_for_spec(self, s)
        # Stash the resolved instance so the output context provider can read
        # it via the ``instance`` extra; DRF calls get_object before
        # get_serializer_context in the retrieve flow.
        self._resolved_instance = obj
        return obj

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        s: SelectorSpec | KernelSelectorSpec | None = get_class_attr(self, "spec")
        if isinstance(s, KernelSelectorSpec):
            return self._retrieve_kernel_spec(s)
        if (
            not isinstance(s, SelectorSpec)
            or s.selector is None
            or (not s.allow_none and s.affordances is None)
        ):
            return self.retrieve(request, *args, **kwargs)
        # Nullable-resource contract: ``get_object()`` may resolve ``None``
        # (instead of raising ``NotFound``); render it as a literal JSON
        # ``null`` without invoking the output serializer. The same path renders
        # a row with its affordance answers, which DRF's ``retrieve`` cannot add.
        instance = self.get_object()
        if instance is None:
            return _JsonNullResponse()
        serializer = self.get_serializer(instance)
        return Response(add_affordances(s, serializer.data, instance, many=False))

    def _retrieve_kernel_spec(self, spec: KernelSelectorSpec) -> Response:
        """A kernel spec's row, presented by the spec, or ``null`` under ``allow_none``.

        The view's object permission was asked inside the dispatch
        (``dispatch_kernel_selector``), so nothing here reads a row the caller
        may not see.
        """
        result = dispatch_kernel_selector(self, spec)
        self._resolved_instance = result.value
        if result.value is None:
            return _JsonNullResponse()
        # One arc to coverage, so each disjunct is named: a presenter by
        # test_the_spec_s_presenter_renders_the_row, affordances with none by
        # test_affordances_with_no_presenter_are_refused_rather_than_dropped.
        if spec.presenter is not None or spec.affordances is not None:
            return Response(present(spec, result))
        return Response(self.get_serializer(result.value).data)
