"""``@service_action`` decorator — DRF ``@action`` plus service plumbing."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from rest_framework import status as drf_status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.types.discriminated_action import DiscriminatedAction
from django_spec_rest.views.mutation.map_service_error import (
    _AdditionalInputAPIException,
)
from django_spec_rest.views.mutation.utils import (
    dispatch_discriminated_action,
    dispatch_mutation_for_spec,
    resolve_mutation_instance,
    restore_schema_when_handled,
)
from django_spec_rest.views.spec_validation import (
    validate_discriminated_action,
    validate_mutation_view_spec,
)


def _validate_kernel_spec(
    spec: KernelServiceSpec,
    *,
    label: str,
    detail: bool,
    success_status: int | Callable[..., int] | None,
    response_finalizer: Callable[..., Response | None] | None,
    discriminated: bool = False,
) -> None:
    """Ask a kernel spec what a standalone mutation view asks of its own, with no view.

    ``validate_mutation_view_spec`` reads the spec and the view's hooks off a
    class, and the decorated class does not exist yet, so it is handed one
    carrying the spec alone, named for the action so a refusal names it. A
    class with no ``get_service_kwargs`` reads as one overriding it, so the
    kernel's ``check_seeds`` is not asked here: the viewset's seeds and hooks
    are unknown until it is mounted, and ``as_view()`` on a viewset built on
    this package's mixins asks it then, against the viewset's ``pool_seeds``
    (test_service_action's test_a_keyword_the_viewset_s_hook_fills_is_not_refused,
    test_a_decorated_action_s_seeds).
    A detail action with no target selector is refused, since the viewset's
    ``get_object()`` is never asked for a kernel spec's row
    (test_a_detail_action_with_no_target_is_refused). The action's own
    ``success_status`` and ``response_finalizer`` ride on the probe, so they
    are asked what a standalone view's are
    (test_per_action_answers' test_a_status_the_view_cannot_resolve_is_refused_at_decoration).
    ``discriminated`` is that ``spec`` is a variant of a ``DiscriminatedAction``,
    so those answers may declare ``variant``.
    """
    # The registry is the viewset's, unknown here; the probe reads as
    # hooked, so the seed check waits for the viewset's ``as_view()``.
    probe = type(
        label,
        (),
        {
            "spec": spec,
            "success_status": success_status,
            "response_finalizer": response_finalizer,
        },
    )
    validate_mutation_view_spec(
        probe, has_instance=detail, pool_seeds=DEFAULT_POOL_SEEDS, discriminated=discriminated
    )


def _validate_discriminated(
    action: DiscriminatedAction,
    *,
    label: str,
    detail: bool,
    success_status: int | Callable[..., int] | None,
    response_finalizer: Callable[..., Response | None] | None,
) -> None:
    """Ask a ``DiscriminatedAction`` its own shape, then each variant as a plain spec, ``[key]``."""
    validate_discriminated_action(action, label=label)
    for key, variant in action.specs.items():
        _validate_kernel_spec(
            variant,
            label=f"{label}[{key!r}]",
            detail=detail,
            success_status=success_status,
            response_finalizer=response_finalizer,
            discriminated=True,
        )


def service_action(
    spec: KernelServiceSpec | DiscriminatedAction,
    *,
    detail: bool = False,
    methods: list[str] | None = None,
    url_path: str | None = None,
    url_name: str | None = None,
    success_status: int | Callable[..., int] | None = None,
    response_finalizer: Callable[..., Response | None] | None = None,
    **action_kwargs: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Wrap a viewset method as a service-backed custom action.

    The decorated method's body is *not* executed — the decorator supplies
    the handler. The method exists so that ``@service_action`` can attach
    DRF ``@action`` metadata and pick up the action name from ``__name__``.

    Pass a [`ServiceSpec`][django_service_specs.specs.service_spec.ServiceSpec]
    for the service wiring. ``detail``, ``methods``, ``url_path``, ``url_name``,
    and any extra ``**action_kwargs`` are forwarded to DRF's ``@action``, a
    ``lenient_json_body`` among them, which outranks the viewset's for this
    action (test_a_service_action_may_declare_its_own).

    The spec runs through the kernel's own ``dispatch``, as on the standalone
    mutation views: its ``permissions`` are asked there, after the view's own
    classes, a detail action's row is its own target selector's (never
    ``get_object()``), and the answer is its presenter's. The spec runs as
    declared: a ``PATCH`` here is validated whole, and documented so, unless the
    spec declares ``partial``, which is the way to a partial call
    (test_decorated_patch).

    ``success_status`` and ``response_finalizer`` are this action's answer, in
    the shapes the viewset's take (``MutationFlowMixin``), and outrank the
    viewset's, an ``as_view()`` keyword included. Left ``None``, the action
    answers with the viewset's, else ``200``. They are asked at decoration what
    a standalone view's are, and a viewset defining a
    ``get_<action>_success_status`` or ``get_<action>_response_finalizer``
    hook beside one is refused at ``as_view()``: one action, one answer
    (test_per_action_answers). The refusal is this package's viewsets'
    ``as_view()``; on a viewset of DRF's alone the decorator's value answers
    and the hook is never read.

    An [`AdditionalInputRequired`][django_service_specs.services.additional_input_required.AdditionalInputRequired]
    answers ``422`` with its ``schema`` as raised on any viewset, DRF's own
    included. The restore runs inside the exception handler the view asks for,
    so the configured ``EXCEPTION_HANDLER`` runs once, and a ``handle_exception``
    override on the viewset still has the last word on the body.

    A detail action with no target selector is refused here. The spec's
    keywords are checked when its viewset is mounted: ``as_view()`` on a
    viewset built on this package's mixins asks the kernel's ``check_seeds``
    against the viewset's ``pool_seeds``, unless a service-kwargs hook of the
    viewset's may fill what it would refuse. On DRF's own ``GenericViewSet`` or
    ``ViewSet`` nothing asks it, and a seed nobody registers is the first
    request's ``TypeError``.

    A ``DiscriminatedAction`` in place of the spec is asked its own shape here
    and each of its variants as a spec is, and the request chooses which runs;
    a callable ``success_status`` or ``response_finalizer`` may then declare
    ``variant``.
    """
    drf_kwargs: dict[str, Any] = {"detail": detail}
    if methods is not None:
        drf_kwargs["methods"] = methods
    if url_path is not None:
        drf_kwargs["url_path"] = url_path
    if url_name is not None:
        drf_kwargs["url_name"] = url_name
    drf_kwargs.update(action_kwargs)

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn_label = getattr(fn, "__qualname__", repr(fn))
        # The viewset class is unknown at decoration time, so any
        # ``get_<action>_service_kwargs`` / ``get_service_kwargs`` it may
        # carry has to be assumed permissive until its ``as_view()``.
        checks: dict[str, Any] = {
            "label": f"@service_action {fn_label}",
            "detail": detail,
            "success_status": success_status,
            "response_finalizer": response_finalizer,
        }
        if isinstance(spec, DiscriminatedAction):
            _validate_discriminated(spec, **checks)
        else:
            _validate_kernel_spec(spec, **checks)

        @functools.wraps(fn)
        def handler(self: Any, request: Request, *args: Any, **kwargs: Any) -> Response:
            try:
                if isinstance(spec, DiscriminatedAction):
                    return dispatch_discriminated_action(
                        self,
                        request,
                        spec,
                        default_status=drf_status.HTTP_200_OK,
                        render_instance_on_none=detail,
                    )
                instance: Any = resolve_mutation_instance(self, spec) if detail else None
                # The action's ``success_status`` (the one stamped below, else
                # the viewset's) is resolved per request inside the dispatch,
                # since it may be a callable keyed on the result, so the
                # decorator passes only the action default (200).
                return dispatch_mutation_for_spec(
                    self,
                    request,
                    spec,
                    instance=instance,
                    default_status=drf_status.HTTP_200_OK,
                    # Detail actions are update-shaped: a service that mutates in
                    # place and returns ``None`` renders the instance. Non-detail
                    # actions have no instance, so the flag is moot.
                    render_instance_on_none=detail,
                )
            except _AdditionalInputAPIException:
                restore_schema_when_handled(self)
                raise

        # Stash the spec on the handler so schema generators can recover it;
        # the closure is otherwise opaque.
        handler._service_spec = spec  # ty: ignore[unresolved-attribute]
        # Read by ``action_answer`` at dispatch, by ``ServiceAutoSchema`` and by
        # the viewset's ``as_view()``. Stamped rather than handed to DRF's
        # ``@action``, whose keywords a router hands ``as_view()``: there they
        # would answer for the route only under a router.
        handler._success_status = success_status  # ty: ignore[unresolved-attribute]
        handler._response_finalizer = response_finalizer  # ty: ignore[unresolved-attribute]
        return action(**drf_kwargs)(handler)

    return decorator
