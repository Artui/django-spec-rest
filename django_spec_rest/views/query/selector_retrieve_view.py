"""``GET`` detail endpoint backed by a kernel selector spec or DRF lookup."""

from __future__ import annotations

from typing import Any, ClassVar

from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.selector_kind import SelectorKind
from rest_framework.generics import GenericAPIView
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.selectors.utils import dispatch_selector_for_spec, present_kernel_row
from django_spec_rest.views.spec_validation import validate_selector_view_spec
from django_spec_rest.views.utils import _JsonNullResponse, get_class_attr


class SelectorRetrieveView(RetrieveModelMixin, GenericAPIView):
    """``GET`` endpoint that returns a single object.

    A kernel ``SelectorSpec`` on ``spec`` runs through the kernel's own
    ``dispatch`` and is presented by its own ``presenter``, with the affordance
    answers it declares. Its selector replaces ``get_object()``: a miss is a
    404, or, when the spec sets ``allow_none=True``, a ``200`` with a JSON
    ``null`` body presented by nothing (the nullable-resource contract). A spec
    declaring neither presenter nor affordances is rendered by the view's
    ``serializer_class``.

    ``spec = None`` (the default) keeps ``get_object()``, standard DRF lookup
    using ``queryset`` and ``lookup_field``, as vanilla DRF.
    """

    spec: ClassVar[SelectorSpec | None] = None

    @classmethod
    def as_view(cls, **initkwargs: Any) -> Any:
        validate_selector_view_spec(
            cls, expected_kind=SelectorKind.RETRIEVE, hooks_base=SelectorRetrieveView
        )
        return super().as_view(**initkwargs)

    def get_selector_kwargs(self) -> dict[str, Any]:
        return {}

    def get_object(self) -> Any:
        """Resolve the target row through the spec's selector, if one is set.

        **``filter_backends`` do not apply here.** DRF runs
        ``filter_queryset()`` inside its own ``get_object()``, so overriding
        that method - this view, or any hand-written override - drops them.
        A tenant-scoping backend in ``DEFAULT_FILTER_BACKENDS`` scopes a
        sibling list view and not this lookup. Scope the selector's own
        queryset, or declare the rule as ``SelectorSpec.filter_set``, which
        the dispatcher applies on both the list and the retrieve path.
        """
        s: SelectorSpec | None = get_class_attr(self, "spec")
        if s is None:
            return super().get_object()
        return dispatch_selector_for_spec(self, s)

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        s: SelectorSpec | None = get_class_attr(self, "spec")
        if s is None:
            return self.retrieve(request, *args, **kwargs)
        # The row and its body, presented by the spec, shared with the
        # viewset's ``retrieve``. The view's object permission was asked
        # inside the dispatch, so nothing here reads a row the caller may
        # not see; ``None`` is a miss under ``allow_none``.
        row, data = present_kernel_row(self, s)
        return _JsonNullResponse() if row is None else Response(data)
