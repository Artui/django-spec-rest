from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any, Literal

from django.core.exceptions import ImproperlyConfigured, SuspiciousOperation
from django.db.models import Model
from django.http import HttpResponseBase
from django.http.request import UnreadablePostError
from django_service_specs.dispatch.present import present
from django_service_specs.pool.resolve_callable_kwargs import resolve_callable_kwargs
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from django_service_specs.types.unset import UNSET
from rest_framework import status as drf_status
from rest_framework.exceptions import NotFound, ParseError, UnsupportedMediaType
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.dispatch.kernel_edge import (
    _DENIALS,
    _RAISED_REFUSALS,
    answering_refusals,
    dispatch_kernel_spec,
    judge_without_arguments,
)
from django_spec_rest.service_specs.kernel_spec_variant import kernel_spec_variant
from django_spec_rest.types.discriminated_action import DiscriminatedAction
from django_spec_rest.types.view_hooks import ViewHooks
from django_spec_rest.views.mutation.apply_response_finalizer import (
    apply_response_finalizer,
)
from django_spec_rest.views.mutation.map_service_error import (
    _AdditionalInputAPIException,
)
from django_spec_rest.views.mutation.resolve_success_status import resolve_success_status
from django_spec_rest.views.utils import (
    action_answer,
    presented_response,
    resolve_view_hooks,
    view_call_context,
    view_pool_seeds,
)

_FAILED_BODY_READS = (ParseError, UnsupportedMediaType, SuspiciousOperation, UnreadablePostError)
"""What reading ``request.data`` raises for what a client sent, and a view hook may read it.

DRF's two, and Django's own: too many form fields or an oversized body, a
``SuspiciousOperation``, and a client gone mid-read. Each held by a case of
test_a_refused_caller_whatever_the_body's
test_a_refused_caller_is_refused_where_a_view_hook_reads_the_body_first (the
first two), test_a_refused_caller_is_refused_where_a_hook_s_read_raises_django_s_own
and test_a_refused_caller_is_refused_where_a_hook_s_read_finds_the_client_gone."""


def status_for_a_body(status: int) -> int:
    """The status a mutation's response goes out under when it carries a body."""
    return drf_status.HTTP_200_OK if status == drf_status.HTTP_204_NO_CONTENT else status


def dispatch_mutation_for_spec(
    view: Any,
    request: Request,
    spec: KernelServiceSpec,
    *,
    instance: Any,
    default_status: int,
    render_instance_on_none: bool,
    partial: bool = False,
    variant: str | None = None,
) -> HttpResponseBase:
    """One ``ServiceSpec`` call over HTTP: the kernel's ``dispatch``, then DRF's response."""
    resolved: Any = None if instance is UNSET else instance
    result = dispatch_kernel_spec(
        kernel_spec_variant(spec, partial=True if partial else None),
        view=view,
        request=request,
        call_context=view_call_context(view, request),
        target=UNSET if instance is None else instance,
        view_hooks=_view_hooks(view, request, spec, instance=resolved),
        on_target=lambda found: _object_permissions(view, request, found),
        pool_seeds=view_pool_seeds(view),
    )
    if result.kind == "not_found":
        raise NotFound()
    if (
        result.value is None
        and result.instance is not None
        and render_instance_on_none
        and spec.presenter is not None
        and spec.output_selector_spec is None
    ):
        result = dataclasses.replace(result, value=result.instance)
    with answering_refusals():
        presented = present(spec, result)
    success_status = action_answer(view, "success_status")
    pool: dict[str, Any] = {"request": request, "view": view, "result": result.service_result}
    if result.instance is not None:
        pool["instance"] = result.instance
    if variant is not None:
        pool["variant"] = variant
    status = resolve_success_status(success_status, default=default_status, pool=pool)
    if presented is None:
        response = Response(
            status=drf_status.HTTP_204_NO_CONTENT if success_status is None else status
        )
    else:
        response = presented_response(presented, status=status_for_a_body(status))
    return apply_response_finalizer(
        action_answer(view, "response_finalizer"),
        response,
        request=request,
        view=view,
        result=result.service_result,
        instance=result.instance,
        data=result.data,
        variant=variant,
    )


def _view_hooks(
    view: Any, request: Request, spec: KernelServiceSpec, *, instance: Any
) -> ViewHooks:
    """The view's hook chains for this call; a failed body read is judged where a hook made it."""
    try:
        return resolve_view_hooks(view, request, instance=instance)
    except _FAILED_BODY_READS:
        with answering_refusals(request) as refused:
            refused.spec = spec
            judge_without_arguments(
                spec,
                principal=request.user,
                call_context=view_call_context(view, request),
                pool_seeds=view_pool_seeds(view),
            )
        raise


def dispatch_discriminated_action(
    view: Any,
    request: Request,
    action: DiscriminatedAction,
    *,
    default_status: int,
    render_instance_on_none: bool,
    partial: bool = False,
) -> HttpResponseBase:
    """Serve a ``DiscriminatedAction`` request: refuse, choose, then run the chosen variant."""
    _refuse_a_caller_every_variant_refuses(view, request, action)
    key = _chosen_key(view, request, action)
    chosen = action.specs[key]
    return dispatch_mutation_for_spec(
        view,
        request,
        chosen,
        instance=resolve_mutation_instance(view, chosen),
        default_status=default_status,
        render_instance_on_none=render_instance_on_none,
        partial=partial,
        variant=key,
    )


def _refuse_a_caller_every_variant_refuses(
    view: Any, request: Request, action: DiscriminatedAction
) -> None:
    """Raise the first variant's denial where every variant refuses the caller, the body unread."""
    call_context = view_call_context(view, request)
    denials: list[tuple[KernelServiceSpec, Exception]] = []
    for spec in action.specs.values():
        try:
            judge_without_arguments(
                spec,
                principal=request.user,
                call_context=call_context,
                pool_seeds=view_pool_seeds(view),
            )
        except (*_DENIALS, *_RAISED_REFUSALS) as denial:
            denials.append((spec, denial))
    if len(denials) == len(action.specs):
        first, denial = denials[0]
        with answering_refusals(request) as refused:
            refused.spec = first
            raise denial


def _chosen_key(view: Any, request: Request, action: DiscriminatedAction) -> str:
    """The key ``action``'s discriminator answers for this request, one of its ``specs``."""
    discriminator = action.discriminator
    with answering_refusals(request):
        key = discriminator(
            **resolve_callable_kwargs(
                discriminator,
                {
                    "request": request,
                    "data": request.data,
                    "user": request.user,
                    "view": view,
                    "call_context": view_call_context(view, request),
                },
            )
        )
    if not isinstance(key, str) or key not in action.specs:
        raise ImproperlyConfigured(
            f"{type(view).__name__}: the discriminator of action {view.action!r} answered "
            f"{key!r}, which is none of {sorted(action.specs)}."
        )
    return key


def _object_permissions(view: Any, request: Request, found: Any) -> None:
    """The view's DRF object permissions, asked of the row a spec's own lookup found."""
    if isinstance(found, Model):
        view.check_object_permissions(request, found)


def resolve_mutation_instance(view: Any, spec: KernelServiceSpec) -> Any:
    """Resolve the mutation target, or defer to the core.

    A spec's target is its own target selector's, or none: the view's
    ``get_object()`` is never asked for one, because the kernel takes a target
    only where the spec declares the selector that would find it, and refuses
    one handed to a spec declaring none. A standalone update or delete view
    refuses such a spec at ``as_view()``; a caller that check never reaches (a
    viewset's action, ``@service_action``) is handed no row
    (test_service_update_view's test_a_kernel_spec_with_no_target_selector_is_handed_no_row).

    Returns: ``None`` for a **bulk** spec (``many=True`` or a
        ``collection_selector_spec``): there is no single instance. ``UNSET`` when
        the spec carries an ``instance_selector_spec``: *the core resolves it*,
        with the right kwarg pool, error label and reserved-seed strip, and the
        view's object permissions are asked of the row it finds. ``None`` for a
        spec with no target at all.

    **``filter_backends`` do not apply**: DRF runs ``filter_queryset()`` inside
    its own ``get_object()``, which a spec's lookup bypasses, exactly as a
    hand-written ``get_object()`` override does. A tenant-scoping backend in
    ``DEFAULT_FILTER_BACKENDS`` therefore does not narrow the row a PATCH or
    DELETE may reach here, while the sibling list action stays scoped. Put the
    scoping in the selector's own queryset.
    """
    return UNSET if mutation_target_source(spec) == "instance_selector" else None


def mutation_target_source(spec: KernelServiceSpec) -> Literal["bulk", "instance_selector"] | None:
    """Where a mutation's target comes from, as ``resolve_mutation_instance`` decides it."""
    if spec.many or spec.collection_selector_spec is not None:
        return "bulk"
    if spec.instance_selector_spec is not None:
        return "instance_selector"
    return None


def restore_raised_schema(exc: Exception, response: Response) -> Response:
    """Put an ``AdditionalInputRequired`` schema back into the body as it was raised."""
    data: Any = getattr(response, "data", None)
    if (
        isinstance(exc, _AdditionalInputAPIException)
        and isinstance(data, dict)
        and "schema" in data
    ):
        response.data = {**data, "schema": exc.schema}
    return response


class _ServesRaisedSchema:
    """Runs ``restore_raised_schema`` over every response ``handle_exception`` builds.

    Inherited by ``MutationFlowMixin`` (the three mutation views and the
    viewset mixins), ``_ActionSpecsMixin`` (every viewset base,
    ``ActionSerializerResolver`` included) and the two selector views, which
    between them are every class the package ships that maps a ``ServiceError``
    into a response (test_a_selector_asking_for_more_input's
    test_a_selector_view_serves_the_schema_as_raised). Defined once, so a class
    inheriting two of them runs it once.

    It runs only where it precedes DRF's view in the bases: in
    ``class V(GenericViewSet, ActionSerializerResolver)``, ``APIView``'s own
    ``handle_exception`` answers first and never calls this one. Nothing the
    package ships is composed that way. A user who lists one of its mixins after
    ``GenericViewSet`` gets DRF's method, and that mixin's own actions serve the
    schema stringified; ``@service_action`` restores it itself on any viewset.
    The restoring half is held by
    test_service_action_serves_the_schema_as_raised_on_any_viewset.
    """

    def handle_exception(self, exc: Exception) -> Response:
        return restore_raised_schema(
            exc,
            super().handle_exception(exc),  # ty: ignore[unresolved-attribute]
        )


def restore_schema_when_handled(view: Any) -> None:
    """Have the exception handler this request's view runs put the raised schema back."""
    get_exception_handler: Callable[[], Callable[..., Any]] = view.get_exception_handler

    def restoring_exception_handler() -> Callable[[Exception, dict[str, Any]], Response | None]:
        # Via the bound method, so the viewset's own ``get_exception_handler`` still chooses.
        handler: Callable[..., Any] = get_exception_handler()

        def restoring(exc: Exception, context: dict[str, Any]) -> Response | None:
            return restore_raised_schema(exc, handler(exc, context))

        return restoring

    view.get_exception_handler = restoring_exception_handler
