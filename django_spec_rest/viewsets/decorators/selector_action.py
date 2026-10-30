"""``@selector_action`` decorator — DRF ``@action`` plus selector plumbing."""

from __future__ import annotations

import functools
from collections.abc import Callable, Mapping
from typing import Any

from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.dispatch.renderable_serializer_class import renderable_serializer_class
from django_spec_rest.selectors.utils import (
    dispatch_selector_for_spec,
    present_kernel_list,
    present_kernel_row,
)
from django_spec_rest.types.selector_kind import SelectorKind
from django_spec_rest.types.selector_spec import SelectorSpec
from django_spec_rest.views.spec_validation import (
    validate_selector_spec,
    validate_selector_view_spec,
)
from django_spec_rest.views.utils import (
    _JsonNullResponse,
    add_affordances,
    resolve_serializer_context,
)


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
    spec: SelectorSpec[Any, Any] | KernelSelectorSpec,
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
    collection action (``detail=False``) whose selector returns an iterable,
    flowing through ``self.paginate_queryset`` / ``self.get_paginated_response``
    when pagination is configured and serialized ``many=True`` otherwise;
    ``SelectorKind.RETRIEVE`` is a detail action (``detail=True``) whose
    selector returns a single object, or ``None`` / raises
    ``ObjectDoesNotExist`` for a 404 -- or, when the spec sets
    ``allow_none=True``, a ``200`` with a JSON ``null`` body, the output
    serializer skipped, as the retrieve view and mixin serve it. For a URL shape
    that doesn't match the response shape, fall back to DRF's plain ``@action``
    and write the dispatch yourself.

    Output serialization uses ``spec.output_serializer`` when set, falling back
    to ``self.get_serializer(...)``.

    A kernel ``SelectorSpec`` runs through the kernel's own ``dispatch``, as on
    the standalone selector views: its ``permissions`` are asked there, after
    the view's own classes, and the view's object permission of the row a
    RETRIEVE finds. Its ``presenter`` renders the row or the page's rows, or
    the viewset's ``get_serializer`` where it declares neither presenter nor
    affordances.
    """
    is_retrieve = spec.kind is SelectorKind.RETRIEVE

    drf_kwargs: dict[str, Any] = {"detail": is_retrieve}
    if methods is not None:
        drf_kwargs["methods"] = methods
    if url_path is not None:
        drf_kwargs["url_path"] = url_path
    if url_name is not None:
        drf_kwargs["url_name"] = url_name
    if isinstance(spec, SelectorSpec) and spec.permission_classes is not None:
        drf_kwargs["permission_classes"] = list(spec.permission_classes)
    drf_kwargs.update(action_kwargs)

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn_label = getattr(fn, "__qualname__", repr(fn))
        if isinstance(spec, KernelSelectorSpec):
            _validate_kernel_spec(spec, label=f"@selector_action {fn_label}")
        else:
            validate_selector_spec(spec, label=f"@selector_action {fn_label}")

        @functools.wraps(fn)
        def handler(self: Any, request: Request, *args: Any, **kwargs: Any) -> Response:
            if isinstance(spec, KernelSelectorSpec):
                return _serve_kernel_spec(self, spec)
            if is_retrieve:
                instance = dispatch_selector_for_spec(self, spec)
                if instance is None:
                    # Only an ``allow_none`` spec gets here with ``None``; any
                    # other miss raised ``NotFound`` inside dispatch. Serializing
                    # it would publish a row of empty fields for a row that does
                    # not exist, so the miss is the same ``null`` the retrieve
                    # view and mixin serve.
                    return _JsonNullResponse()
                serializer = _build_serializer(
                    self, spec, instance, many=False, extras={"instance": instance}
                )
                return Response(add_affordances(spec, serializer.data, instance, many=False))

            result = dispatch_selector_for_spec(self, spec)
            page = self.paginate_queryset(result) if hasattr(self, "paginate_queryset") else None
            if page is not None:
                serializer = _build_serializer(self, spec, page, many=True, extras={"page": page})
                return self.get_paginated_response(
                    add_affordances(spec, serializer.data, page, many=True)
                )
            serializer = _build_serializer(self, spec, result, many=True, extras={"page": result})
            return Response(add_affordances(spec, serializer.data, result, many=True))

        # Stash the spec so schema generators can recover it; the closure is
        # otherwise opaque.
        handler._selector_spec = spec  # ty: ignore[unresolved-attribute]
        return action(**drf_kwargs)(handler)

    return decorator


def _serve_kernel_spec(view: Any, spec: KernelSelectorSpec) -> Response:
    """A kernel spec's answer: its row, ``null`` under ``allow_none``, or its rows, a page where paginated.

    No filter backend applies to the set, as none applies to a drfs spec's
    here: DRF's ``@action`` leaves filtering to its handler.
    """
    if spec.kind is SelectorKind.RETRIEVE:
        row, data = present_kernel_row(view, spec)
        return _JsonNullResponse() if row is None else Response(data)
    data, paginated = present_kernel_list(view, spec, filtered=False)
    return view.get_paginated_response(data) if paginated else Response(data)


def _build_serializer(
    view: Any,
    spec: SelectorSpec[Any, Any],
    instance: Any,
    *,
    many: bool,
    extras: Mapping[str, Any],
) -> Any:
    """Instantiate the response serializer for a ``@selector_action`` result.

    ``spec.output_serializer`` wins when set, matching the standalone selector views;
    otherwise the viewset's ``get_serializer(...)`` keeps existing
    [`ActionSerializerResolver`][django_spec_rest.viewsets.action_serializer_resolver.ActionSerializerResolver]
    wiring in play. Context flows through the DRF default →
    ``get_output_serializer_context`` → ``get_<action>_output_serializer_context``
    chain, both hooks optional. ``extras`` carries the resolved data — ``instance`` for
    a detail action, ``page`` for a collection one — offered to each context provider by
    keyword when it declares the name."""
    if spec.output_serializer is not None:
        action: str | None = getattr(view, "action", None)
        action_hook: str | None = f"get_{action}_output_serializer_context" if action else None
        context = resolve_serializer_context(
            view,
            view.request,
            direction_hook="get_output_serializer_context",
            action_hook=action_hook,
            spec_provider=spec.output_serializer_context,
            extras=extras,
        )
        return renderable_serializer_class(spec.output_serializer)(
            instance, many=many, context=context
        )
    return view.get_serializer(instance, many=many)
