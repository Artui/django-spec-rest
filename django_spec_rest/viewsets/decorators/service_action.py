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
    """Ask a kernel spec what a standalone mutation view asks of its own, with no view."""
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
    """Wrap a viewset method as a service-backed custom action."""
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
        # Viewset unknown here, so its ``get_<action>_service_kwargs`` is assumed permissive.
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
                # ``success_status`` resolves per request, so only the default (200) passes here.
                return dispatch_mutation_for_spec(
                    self,
                    request,
                    spec,
                    instance=instance,
                    default_status=drf_status.HTTP_200_OK,
                    render_instance_on_none=detail,
                )
            except _AdditionalInputAPIException:
                restore_schema_when_handled(self)
                raise

        handler._service_spec = spec  # ty: ignore[unresolved-attribute]
        handler._success_status = success_status  # ty: ignore[unresolved-attribute]
        handler._response_finalizer = response_finalizer  # ty: ignore[unresolved-attribute]
        return action(**drf_kwargs)(handler)

    return decorator
