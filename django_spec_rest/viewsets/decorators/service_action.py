"""``@service_action`` decorator — DRF ``@action`` plus service plumbing."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from rest_framework import status as drf_status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.views.mutation.map_service_error import (
    _AdditionalInputAPIException,
)
from django_spec_rest.views.mutation.utils import (
    dispatch_mutation_for_spec,
    resolve_mutation_instance,
    restore_raised_schema,
)
from django_spec_rest.views.spec_validation import validate_mutation_view_spec


def _restore_schema_when_handled(view: Any) -> None:
    """Have the exception handler this request's view runs put the raised schema back.

    The restore is otherwise a ``handle_exception`` override on this package's
    bases, which a decorated method on DRF's own viewsets never reaches, and
    which DRF's own method shadows where one of them is listed after
    ``GenericViewSet``. The decorator owns no class, but it runs on the view
    instance ``APIView.dispatch`` is about to hand the error to.

    So that instance's ``get_exception_handler`` is wrapped, for that request,
    and the error is re-raised rather than answered here.
    ``APIView.handle_exception`` asks for the handler as it always does, and gets
    one that runs the handler it would have got and then restores the schema on
    the response that built. Everything else follows from where that is:

    - The handler runs once and sees DRF's ``ErrorDetail`` leaves, and one that
      declines the error by returning ``None`` still returns ``None``, so DRF
      raises the error once, as on any other view. Answering from inside the
      action instead would hand a declined error back to ``dispatch``, which
      runs the handler a second time. Held by
      test_a_handler_declining_the_error_runs_once_on_any_viewset.
    - The restore runs inside ``APIView.handle_exception``, beneath every
      ``handle_exception`` in the class's chain, so an override of it has the
      last word on the body on every viewset. Wrapping ``handle_exception``
      itself ran the restore after the whole chain and undid what an override
      wrote to ``schema``. Held by
      test_an_overriding_handle_exception_has_the_last_word_on_every_route.
    - On this package's bases ``_ServesRaisedSchema`` restores again on the way
      out of ``APIView.handle_exception``. No ``handle_exception`` of this
      package's runs between the two, and each writes the schema as raised, so
      the second leaves the body as the first left it.

    The restore inside the handler is what serves the schema as raised where
    the class's chain never reaches ``_ServesRaisedSchema``. Held by
    test_service_action_serves_the_schema_as_raised_on_any_viewset, whose
    ``GenericViewSet``, ``ViewSet`` and ``GenericViewSet, ActionSerializerResolver``
    cases are served stringified without it.
    """
    get_exception_handler: Callable[[], Callable[..., Any]] = view.get_exception_handler

    def restoring_exception_handler() -> Callable[[Exception, dict[str, Any]], Response | None]:
        # Asked through the bound method when ``handle_exception`` asks, as DRF
        # asks it, so a ``get_exception_handler`` of the viewset's own still
        # chooses the handler. Held by
        # test_a_viewsets_own_exception_handler_still_answers_on_any_viewset.
        handler: Callable[..., Any] = get_exception_handler()

        def restoring(exc: Exception, context: dict[str, Any]) -> Response | None:
            return restore_raised_schema(exc, handler(exc, context))

        return restoring

    view.get_exception_handler = restoring_exception_handler


def _validate_kernel_spec(spec: KernelServiceSpec, *, label: str, detail: bool) -> None:
    """Ask a kernel spec what a standalone mutation view asks of its own, with no view.

    ``validate_mutation_view_spec`` reads the spec and the view's hooks off a
    class, and the decorated class does not exist yet, so it is handed one
    carrying the spec alone, named for the action so a refusal names it. A
    class with no ``get_service_kwargs`` reads as one overriding it, so the
    kernel's ``check_seeds`` is not asked: a hook of the viewset's own may fill
    the keyword it would refuse, and a mixin base would have it refused anyway
    (test_service_action's test_a_keyword_the_viewset_s_hook_fills_is_not_refused).
    A detail action with no target selector is refused, since the viewset's
    ``get_object()`` is never asked for a kernel spec's row
    (test_a_detail_action_with_no_target_is_refused).
    """
    validate_mutation_view_spec(type(label, (), {"spec": spec}), has_instance=detail)


def service_action(
    spec: KernelServiceSpec,
    *,
    detail: bool = False,
    methods: list[str] | None = None,
    url_path: str | None = None,
    url_name: str | None = None,
    **action_kwargs: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Wrap a viewset method as a service-backed custom action.

    The decorated method's body is *not* executed — the decorator supplies
    the handler. The method exists so that ``@service_action`` can attach
    DRF ``@action`` metadata and pick up the action name from ``__name__``.

    Pass a [`ServiceSpec`][django_service_specs.specs.service_spec.ServiceSpec]
    for the service wiring. ``detail``, ``methods``, ``url_path``, ``url_name``,
    and any extra ``**action_kwargs`` are forwarded to DRF's ``@action``.

    The spec runs through the kernel's own ``dispatch``, as on the standalone
    mutation views: its ``permissions`` are asked there, after the view's own
    classes, a detail action's row is its own target selector's (never
    ``get_object()``), and the answer is its presenter's, under the viewset's
    ``success_status`` (``200`` by default) and through its
    ``response_finalizer``.

    An [`AdditionalInputRequired`][django_service_specs.services.additional_input_required.AdditionalInputRequired]
    answers ``422`` with its ``schema`` as raised on any viewset, DRF's own
    included. The restore runs inside the exception handler the view asks for,
    so the configured ``EXCEPTION_HANDLER`` runs once, and a ``handle_exception``
    override on the viewset still has the last word on the body.
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
        # carry has to be assumed permissive.
        _validate_kernel_spec(spec, label=f"@service_action {fn_label}", detail=detail)

        @functools.wraps(fn)
        def handler(self: Any, request: Request, *args: Any, **kwargs: Any) -> Response:
            try:
                instance: Any = resolve_mutation_instance(self, spec) if detail else None
                # The viewset's ``success_status`` is resolved per request inside
                # the dispatch, since it may be a callable keyed on the result,
                # so the decorator passes only the action default (200).
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
                _restore_schema_when_handled(self)
                raise

        # Stash the spec on the handler so schema generators can recover it;
        # the closure is otherwise opaque.
        handler._service_spec = spec  # ty: ignore[unresolved-attribute]
        return action(**drf_kwargs)(handler)

    return decorator
