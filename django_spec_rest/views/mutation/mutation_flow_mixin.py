"""``MutationFlowMixin`` — shared service-action flow for views and viewsets."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, ClassVar

from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.dispatch.kernel_edge import runs_on_kernel
from django_spec_rest.types.service_spec import ServiceSpec
from django_spec_rest.views.mutation.utils import (
    _ServesRaisedSchema,
    dispatch_mutation_for_spec,
)


class MutationFlowMixin(_ServesRaisedSchema):
    """Provides ``_run_mutation`` for service-backed views and viewset mixins.

    The flow itself lives in ``dispatch_mutation_for_spec``, so
    ``@service_action`` can reach it without being a class; this mixin is the OO
    entry point that the per-action mixins (``ServiceCreateMixin`` and friends)
    and the standalone single-purpose views compose, calling
    ``self._run_mutation(...)`` after resolving their per-action spec.

    Four hook chains feed a mutation, each layered view-wide → per-action →
    per-spec and merged with ``dict.update`` so the more specific hook wins on
    overlapping keys:

    - extra service kwargs: ``get_service_kwargs`` →
      ``get_<action>_service_kwargs`` → ``ServiceSpec.kwargs``.
    - the *serializer's* input dict, merged on top of ``request.data`` before
      validation: ``get_input_data`` → ``get_<action>_input_data`` →
      ``ServiceSpec.input_data``.
    - the input serializer's ``context=``: ``get_serializer_context`` (DRF's
      own) → ``get_input_serializer_context`` →
      ``get_<action>_input_serializer_context`` →
      ``ServiceSpec.input_serializer_context``.
    - the output serializer's ``context=``: the same chain with ``output`` in
      place of ``input``, applied during response rendering.

    The per-action layer reads ``self.action``, so it applies to viewsets only.

    For a kernel spec, which declares neither, the response's two HTTP hooks
    are the view's: ``success_status`` and ``response_finalizer`` below, read
    off the class unbound, as a drfs spec's fields of those names are read off
    the spec. A drfs spec's own fields are what its view reads, and these are
    not.
    """

    success_status: ClassVar[int | Callable[..., int] | None] = None
    """A kernel spec's success status: an ``int``, or a callable declaring any of
    ``result`` / ``instance`` / ``request`` / ``view``, or ``None`` for the
    action's default (``201`` create, ``200`` update, ``204`` delete). A body
    never goes out under ``204``, so a status resolving to it answers ``200``
    with one; set, it applies to an answer with nothing to present too
    (test_callable_success_status)."""

    response_finalizer: ClassVar[Callable[..., Response | None] | None] = None
    """A kernel spec's post-presentation hook on a ``2xx``: declares any of
    ``response`` / ``result`` / ``request`` / ``view`` / ``instance`` / ``data``
    and returns a ``Response`` to replace the one built, or ``None`` to keep it
    (test_response_finalizer)."""

    def get_service_kwargs(self) -> dict[str, Any]:
        """Hook for additional kwargs available to every mutation service."""
        return {}

    def get_input_data(self, request: Request) -> Mapping[str, Any]:
        """Hook for extras merged on top of ``request.data`` before validation."""
        return {}

    def get_input_serializer_context(self) -> dict[str, Any]:
        """Hook for the ``context=`` dict passed to the *input* serializer.

        Defaults to ``get_serializer_context``, so overriding the
        DRF-standard hook flows into input validation automatically; override
        here for keys visible only during input validation.
        """
        return self.get_serializer_context()  # ty: ignore[unresolved-attribute]

    def get_output_serializer_context(self) -> dict[str, Any]:
        """Hook for the ``context=`` dict passed to the *output* serializer.

        Defaults to ``get_serializer_context``, so overriding the
        DRF-standard hook flows into response rendering automatically; override
        here for keys visible only during response rendering.
        """
        return self.get_serializer_context()  # ty: ignore[unresolved-attribute]

    def get_permissions(self) -> list[Any]:
        """Honor ``spec.permission_classes`` on standalone mutation views.

        Standalone ``Service*View`` subclasses carry ``spec`` as a class
        attribute; when it sets ``permission_classes`` those win over the view's
        class-level ones, and ``None`` falls through.

        A kernel spec has no ``permission_classes``: it declares its checks as
        ``permissions``, which the kernel's ``dispatch`` asks itself, so its
        view answers its own classes, which DRF asks before the view runs, as
        for a drfs spec setting none. Both apply, the view's first
        (test_kernel_views' test_the_view_s_own_classes_refuse_before_the_spec_runs).
        """
        spec: ServiceSpec[Any, Any, Any] | None = getattr(self, "spec", None)
        if runs_on_kernel(spec):
            return super().get_permissions()  # ty: ignore[unresolved-attribute]
        if spec is not None and spec.permission_classes is not None:
            return [permission() for permission in spec.permission_classes]
        return super().get_permissions()  # ty: ignore[unresolved-attribute]

    def _run_mutation(
        self,
        request: Request,
        spec: ServiceSpec[Any, Any, Any],
        *,
        instance: Any,
        default_status: int,
        render_instance_on_none: bool = False,
        partial: bool = False,
    ) -> Response:
        return dispatch_mutation_for_spec(
            self,
            request,
            spec,
            instance=instance,
            default_status=default_status,
            render_instance_on_none=render_instance_on_none,
            partial=partial,
        )
