from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.selectors.utils import (
    dispatch_kernel_selector,
    present_kernel_list,
    present_kernel_row,
)
from django_spec_rest.types.discriminated_action import DiscriminatedAction
from django_spec_rest.views.mutation.map_service_error import (
    _AdditionalInputAPIException,
)
from django_spec_rest.views.mutation.utils import restore_schema_when_handled
from django_spec_rest.views.utils import _JsonNullResponse


def selector_action(
    spec: KernelSelectorSpec,
    *,
    methods: list[str] | None = None,
    url_path: str | None = None,
    url_name: str | None = None,
    **action_kwargs: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Wrap a viewset method as a selector-backed custom action."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        _refuse_a_spec_that_is_not_a_selector(spec, fn)
        drf_kwargs: dict[str, Any] = {"detail": spec.kind is SelectorKind.RETRIEVE}
        if methods is not None:
            drf_kwargs["methods"] = methods
        if url_path is not None:
            drf_kwargs["url_path"] = url_path
        if url_name is not None:
            drf_kwargs["url_name"] = url_name
        drf_kwargs.update(action_kwargs)

        @functools.wraps(fn)
        def handler(self: Any, request: Request, *args: Any, **kwargs: Any) -> Response:
            try:
                return _serve_kernel_spec(self, spec)
            except _AdditionalInputAPIException:
                restore_schema_when_handled(self)
                raise

        # Stash the spec so schema generators can recover it; the closure is otherwise opaque.
        handler._selector_spec = spec  # ty: ignore[unresolved-attribute]
        return action(**drf_kwargs)(handler)

    return decorator


def _refuse_a_spec_that_is_not_a_selector(spec: Any, fn: Callable[..., Any]) -> None:
    """``ImproperlyConfigured`` naming the action, for a ``spec`` that is not a ``SelectorSpec``."""
    label = f"@selector_action {getattr(fn, '__qualname__', repr(fn))}"
    if isinstance(spec, KernelSelectorSpec):
        return
    if isinstance(spec, (KernelServiceSpec, DiscriminatedAction)):
        raise ImproperlyConfigured(
            f"{label}: the spec is a {type(spec).__name__}, which writes, and "
            "@selector_action serves a read. Decorate the action with @service_action."
        )
    raise ImproperlyConfigured(
        f"{label}: the spec is a {type(spec).__name__}, and @selector_action serves a "
        "SelectorSpec. Pass the SelectorSpec the action reads through."
    )


def _serve_kernel_spec(view: Any, spec: KernelSelectorSpec) -> Response:
    """A kernel spec's answer: its row, ``null`` under ``allow_none``, or its rows, a page where paginated."""
    if spec.kind is SelectorKind.RETRIEVE:
        row, data = present_kernel_row(view, spec)
        return _JsonNullResponse() if row is None else Response(data)
    data, paginated = present_kernel_list(
        view, spec, dispatch_kernel_selector(view, spec), filtered=False
    )
    return view.get_paginated_response(data) if paginated else Response(data)
