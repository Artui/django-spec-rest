"""``GET`` list endpoint backed by a kernel selector spec or DRF queryset."""

from __future__ import annotations

from typing import Any, ClassVar

from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.selector_kind import SelectorKind
from rest_framework.generics import GenericAPIView
from rest_framework.mixins import ListModelMixin
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.selectors.utils import dispatch_selector_for_spec, present_kernel_list
from django_spec_rest.views.spec_validation import validate_selector_view_spec
from django_spec_rest.views.utils import get_class_attr


class SelectorListView(ListModelMixin, GenericAPIView):
    """``GET`` endpoint that delegates to a selector spec or to ``get_queryset()``.

    A kernel ``SelectorSpec`` on ``spec`` runs through the kernel's own
    ``dispatch`` and is presented by its own ``presenter``, the page's rows
    alone when the view paginates, with the affordance answers it declares;
    a spec declaring neither presenter nor affordances is rendered by the
    view's ``serializer_class``, as DRF renders a queryset.

    ``spec = None`` (the default) keeps ``get_queryset()`` and the rest of the
    flow as vanilla DRF. The rest of the list flow (filter backends,
    pagination, response rendering) is the standard DRF ``ListModelMixin``.
    """

    spec: ClassVar[SelectorSpec | None] = None

    @classmethod
    def as_view(cls, **initkwargs: Any) -> Any:
        validate_selector_view_spec(
            cls, expected_kind=SelectorKind.LIST, hooks_base=SelectorListView
        )
        return super().as_view(**initkwargs)

    def get_selector_kwargs(self) -> dict[str, Any]:
        """The default an override is read against, and never called.

        A view overriding it beside a kernel spec is refused at ``as_view()``
        (test_get_selector_kwargs_beside_a_kernel_spec_is_refused_at_as_view):
        the kernel route has no selector overlay to hand its value to.
        """
        return {}

    def get_queryset(self) -> Any:
        s: SelectorSpec | None = get_class_attr(self, "spec")
        if s is None:
            return super().get_queryset()
        return dispatch_selector_for_spec(self, s)

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # The answers are added here rather than in ``get`` so a subclass that
        # extends ``list`` keeps running once its spec declares affordances --
        # the same seam ``SelectorListMixin`` uses.
        s: SelectorSpec | None = get_class_attr(self, "spec")
        if s is None:
            return super().list(request, *args, **kwargs)
        # DRF's ``list`` steps over the set the dispatch read, presented
        # by the spec, shared with the viewset's ``list``.
        data, paginated = present_kernel_list(self, s, filtered=True)
        return self.get_paginated_response(data) if paginated else Response(data)

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.list(request, *args, **kwargs)
