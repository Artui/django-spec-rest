"""``@selector_action`` decorator — DRF ``@action`` plus selector plumbing."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.types.selector_kind import SelectorKind
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.selectors.utils import present_kernel_list, present_kernel_row
from django_spec_rest.views.spec_validation import validate_selector_view_spec
from django_spec_rest.views.utils import _JsonNullResponse


def _validate_kernel_spec(spec: KernelSelectorSpec, *, label: str) -> None:
    """Ask a kernel spec what a standalone selector view asks of its own, with no view.

    ``validate_selector_view_spec`` reads the spec and the view's hooks off a
    class, and the decorated class does not exist yet, so it is handed one
    carrying the spec alone, named for the action so a refusal names it. Its
    ``hooks_base`` is ``object``, which declares no ``get_selector_kwargs``,
    so the class carrying none is not read as overriding it. The kernel's
    ``check_seeds`` is asked in full: the edge hands a kernel selector no
    view hook, so nothing of the viewset's can fill a keyword it refuses
    (test_selector_action's test_a_keyword_nothing_fills_is_refused).
    """
    validate_selector_view_spec(
        type(label, (), {"spec": spec}), expected_kind=spec.kind, hooks_base=object
    )


def selector_action(
    spec: KernelSelectorSpec,
    *,
    methods: list[str] | None = None,
    url_path: str | None = None,
    url_name: str | None = None,
    **action_kwargs: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Wrap a viewset method as a selector-backed custom action.

    The decorated method's body is *not* executed — the decorator supplies the
    handler. The method exists so the decorator can attach DRF ``@action``
    metadata and take the action name from ``__name__``.

    ``spec.kind`` drives both the dispatch shape and the DRF URL shape, so there
    is no separate ``detail=`` to keep in sync. ``SelectorKind.LIST`` is a
    collection action (``detail=False``) whose rows are a page where the view
    paginates; ``SelectorKind.RETRIEVE`` is a detail action (``detail=True``)
    whose row is ``null`` under ``allow_none`` and a 404 otherwise. For a URL
    shape that doesn't match the response shape, fall back to DRF's plain
    ``@action`` and write the dispatch yourself.

    A
    [`SelectorSpec`][django_service_specs.specs.selector_spec.SelectorSpec]
    runs through the kernel's own ``dispatch``, as on the standalone selector
    views: its ``permissions`` are asked there, after the view's own classes,
    and the view's object permission of the row a RETRIEVE finds. Its
    ``presenter`` renders the row or the page's rows, or the viewset's
    ``get_serializer`` where it declares neither presenter nor affordances.
    """
    is_retrieve = spec.kind is SelectorKind.RETRIEVE

    drf_kwargs: dict[str, Any] = {"detail": is_retrieve}
    if methods is not None:
        drf_kwargs["methods"] = methods
    if url_path is not None:
        drf_kwargs["url_path"] = url_path
    if url_name is not None:
        drf_kwargs["url_name"] = url_name
    drf_kwargs.update(action_kwargs)

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn_label = getattr(fn, "__qualname__", repr(fn))
        _validate_kernel_spec(spec, label=f"@selector_action {fn_label}")

        @functools.wraps(fn)
        def handler(self: Any, request: Request, *args: Any, **kwargs: Any) -> Response:
            return _serve_kernel_spec(self, spec)

        # Stash the spec so schema generators can recover it; the closure is
        # otherwise opaque.
        handler._selector_spec = spec  # ty: ignore[unresolved-attribute]
        return action(**drf_kwargs)(handler)

    return decorator


def _serve_kernel_spec(view: Any, spec: KernelSelectorSpec) -> Response:
    """A kernel spec's answer: its row, ``null`` under ``allow_none``, or its rows, a page where paginated.

    No filter backend applies to the set: DRF's ``@action`` leaves filtering to
    its handler.
    """
    if spec.kind is SelectorKind.RETRIEVE:
        row, data = present_kernel_row(view, spec)
        return _JsonNullResponse() if row is None else Response(data)
    data, paginated = present_kernel_list(view, spec, filtered=False)
    return view.get_paginated_response(data) if paginated else Response(data)
