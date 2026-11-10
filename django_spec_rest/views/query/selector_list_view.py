from __future__ import annotations

from typing import Any, ClassVar

from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.selector_kind import SelectorKind
from rest_framework.generics import GenericAPIView
from rest_framework.mixins import ListModelMixin
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.selectors.utils import dispatch_list_once, present_kernel_list
from django_spec_rest.views.mutation.utils import _ServesRaisedSchema
from django_spec_rest.views.spec_validation import validate_selector_view_spec
from django_spec_rest.views.utils import get_class_attr, mounted_view, view_pool_seeds

# The methods ``get`` answers: Django routes a HEAD to ``get`` where a view
# declares no ``head``.
_THE_LIST_S_METHODS = ("GET", "HEAD")


class SelectorListView(_ServesRaisedSchema, ListModelMixin, GenericAPIView):
    """``GET`` endpoint that delegates to a selector spec or to ``get_queryset()``.

    A kernel ``SelectorSpec`` on ``spec`` runs through the kernel's own
    ``dispatch`` and is presented by its own ``presenter``, the page's rows
    alone when the view paginates, with the affordance answers it declares;
    a spec declaring neither presenter nor affordances is rendered by the
    view's ``serializer_class``, as DRF renders a queryset.

    ``get_queryset()`` answers the spec's set to a ``GET`` or ``HEAD`` alone,
    from the one dispatch ``list`` presents, so a permission class asking it
    first does not run the selector twice; to an OPTIONS or any other method
    it is DRF's own, the view's ``queryset``.

    ``spec = None`` (the default) keeps ``get_queryset()`` and the rest of the
    flow as vanilla DRF. The rest of the list flow (filter backends,
    pagination, response rendering) is the standard DRF ``ListModelMixin``.
    """

    spec: ClassVar[SelectorSpec | None] = None

    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS
    """The seeds the spec's callables are resolved with: the kernel's
    ``DEFAULT_POOL_SEEDS`` unless the view registers others, as a class
    attribute or as ``as_view(pool_seeds=...)``. One registry for the view's
    life: ``as_view()`` checks the spec against it, refusing a callable that
    requires a seed it does not register, and every call's checks, target
    lookup and ``dispatch`` are handed that object (test_pool_seeds)."""

    @classmethod
    def as_view(cls, **initkwargs: Any) -> Any:
        # Checked as the instances will be, keywords included (``mounted_view``).
        mounted = mounted_view(cls, initkwargs)
        validate_selector_view_spec(
            mounted, expected_kind=SelectorKind.LIST, pool_seeds=view_pool_seeds(mounted)
        )
        return super().as_view(**initkwargs)

    def get_queryset(self) -> Any:
        s: SelectorSpec | None = get_class_attr(self, "spec")
        # DRF's permissions ask ``get_queryset()`` before any handler, so an OPTIONS got the 400.
        if s is None or self.request.method not in _THE_LIST_S_METHODS:
            return super().get_queryset()
        return dispatch_list_once(self, s).value

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Answers are added here, not in ``get``, so a subclass extending ``list`` keeps running.
        s: SelectorSpec | None = get_class_attr(self, "spec")
        if s is None:
            return super().list(request, *args, **kwargs)
        data, paginated = present_kernel_list(self, s, dispatch_list_once(self, s), filtered=True)
        return self.get_paginated_response(data) if paginated else Response(data)

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.list(request, *args, **kwargs)
