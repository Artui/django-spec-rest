"""Helpers used by the mutation views, viewset mixins, and ``@service_action``.

The HTTP half either side of the kernel's ``dispatch``: view hooks in, response
out. There is deliberately **no** flow runner here: the mutation pipeline lives
in the kernel, and a behaviour that belongs to the *spec* belongs there, or it
will be honoured on one transport and not the other.

``map_service_error`` is re-imported from its own leaf module rather than
defined here, so the edge can map errors without importing this one.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Literal

from django.db.models import Model
from django_service_specs.dispatch.present import present
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from django_service_specs.types.unset import UNSET
from rest_framework import status as drf_status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.dispatch.kernel_edge import (
    answering_refusals,
    dispatch_kernel_spec,
)
from django_spec_rest.service_specs.kernel_spec_variant import kernel_spec_variant
from django_spec_rest.views.mutation.apply_response_finalizer import (
    apply_response_finalizer,
)
from django_spec_rest.views.mutation.map_service_error import (
    _AdditionalInputAPIException,
)
from django_spec_rest.views.mutation.resolve_success_status import resolve_success_status
from django_spec_rest.views.utils import (
    get_class_attr,
    resolve_view_hooks,
    view_call_context,
)


def status_for_a_body(status: int) -> int:
    """The status a mutation's response goes out under when it carries a body.

    A ``204`` carries no body, so a client or proxy is entitled to discard one
    sent under it. A response with something to present answers ``200`` wherever
    its status resolved to ``204``, whether that is a destroy's default or a
    ``success_status`` that is, or returns, ``204``. Any other status carries the
    body as it is.

    The single-row and bulk renderers both ask this, and so does the OpenAPI
    schema for an operation that declares a body, so the status a body is
    documented under is the one it is served under. One comparison, held both
    ways: test_a_destroy_presenting_a_row_answers_200_rather_than_204 answers
    ``204`` with a body without it, and test_service_create_view's
    test_creates_and_returns_201, with every other create answering ``201`` with
    a body, answers ``200`` if it always holds.
    """
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
) -> Response:
    """End-to-end dispatch for one ``ServiceSpec`` call over HTTP: the kernel's ``dispatch``, then DRF's response.

    Used by
    [`MutationFlowMixin`][django_spec_rest.views.mutation.mutation_flow_mixin.MutationFlowMixin],
    the standalone mutation views, and ``@service_action`` so the call shape lives in
    one place. Only the first and last steps are HTTP's.

    - **The target.** A row the view resolved (``get_object()``, which asks
      the view's object permissions) is handed over as ``target``; ``UNSET``
      leaves the lookup to the spec's own target selector, and the view's
      object permissions are asked of what it finds before the service runs,
      as ``get_object()`` asks them (``_object_permissions``). A create hands
      ``None`` and a bulk call ``None``: to the kernel ``None`` is a missing
      row, refused on a ``many`` spec, so either is handed no target at all
      (test_kernel_views'
      test_a_list_body_is_its_rows_and_its_output_selector_s_re_read_is_presented).
    - **The view's hook chains**, its own layers only, through the edge
      (``dispatch_kernel_spec``'s ``view_hooks``).
    - **A ``PATCH``** dispatches the spec's partial variant, the one
      ``kernel_spec_variant`` holds for it: a ``PATCH`` asks for a partial call
      wherever the spec is not one already, and ``partial=True`` forces one on
      a ``PUT`` too; a spec cannot force a ``PATCH`` whole. A Validator that cannot take a partial call (a
      dataclass serializer's) or no Validator at all keeps the spec as it is,
      and the ``PATCH`` is validated whole, as a ``PUT`` is
      (test_service_update_view's test_a_patch_over_a_dataclass_validates_every_field,
      test_a_patch_with_no_validator_runs).
    - **The response.** The spec's presenter presents the result through the
      kernel's ``present``. An update whose service returned ``None`` presents
      its target, as DRF's ``UpdateAPIView`` does (``render_instance_on_none``).
      The status is the view's ``success_status`` over ``default_status``, a
      body never going out under ``204``; then the view's
      ``response_finalizer`` (``MutationFlowMixin``).
    """
    resolved: Any = None if instance is UNSET else instance
    result = dispatch_kernel_spec(
        # ``None``, not ``False``, for a ``PUT``: ``False`` would derive a whole
        # variant of a spec declaring ``partial=True``
        # (test_a_partial_spec_takes_a_put_partially).
        kernel_spec_variant(spec, partial=True if partial else None),
        view=view,
        request=request,
        call_context=view_call_context(view, request),
        target=UNSET if instance is None else instance,
        view_hooks=resolve_view_hooks(view, request, instance=resolved),
        on_target=lambda found: _object_permissions(view, request, found),
    )
    if result.kind == "not_found":
        raise NotFound()
    # One arc to coverage, so each condition is named:
    # test_service_update_view's test_a_service_s_own_row_outranks_its_target
    # (the value), test_service_delete_view's test_a_delete_returning_nothing_answers_204
    # (the caller's intent), test_service_update_view's
    # test_an_update_with_no_presenter_returning_nothing_answers_204 (the
    # presenter) and test_an_output_selector_s_none_is_its_own_beside_the_spec_s_presenter
    # (the re-read, which owns its ``None``: the presenter must be the service
    # spec's for this conjunct alone to decide). The target's is a saving:
    # with none, ``value`` stays ``None``.
    if (
        result.value is None
        and result.instance is not None
        and render_instance_on_none
        and spec.presenter is not None
        and spec.output_selector_spec is None
    ):
        result = dataclasses.replace(result, value=result.instance)
    # Inside the map too: a presenter may refuse what it was asked to
    # present (test_a_presenter_s_refusal_is_answered_by_the_map_too).
    with answering_refusals():
        presented = present(spec, result)
    success_status = get_class_attr(view, "success_status")
    pool: dict[str, Any] = {"request": request, "view": view, "result": result.service_result}
    if result.instance is not None:
        pool["instance"] = result.instance
    status = resolve_success_status(success_status, default=default_status, pool=pool)
    if presented is None:
        # Nothing to present is ``204`` unless the view set a status, which then
        # applies to every answer alike (test_callable_success_status's
        # test_a_callable_status_applies_to_an_empty_answer).
        response = Response(
            status=drf_status.HTTP_204_NO_CONTENT if success_status is None else status
        )
    else:
        response = Response(presented, status=status_for_a_body(status))
    return apply_response_finalizer(
        get_class_attr(view, "response_finalizer"),
        response,
        request=request,
        view=view,
        result=result.service_result,
        instance=result.instance,
        data=result.data,
    )


def _object_permissions(view: Any, request: Request, found: Any) -> None:
    """The view's DRF object permissions, asked of the row a spec's own lookup found.

    Per row, as ``get_object()`` asks them, so a collection target's set and
    a missing row's ``None`` are asked nothing
    (test_bulk_mutations' test_a_queryset_collection_target_is_untouched_by_the_guard),
    while a single row a collection selector returns is
    (test_a_single_row_collection_target_is_object_checked).
    """
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
    """Where a mutation's target comes from, as ``resolve_mutation_instance`` decides it.

    ``None`` is a spec naming no target. The kernel refuses a target selector
    beside ``many=True`` or a collection selector, so ``"bulk"`` never shadows
    ``"instance_selector"``, and the one caller, which asks only for the
    latter, cannot tell ``"bulk"`` from ``None``.
    """
    if spec.many or spec.collection_selector_spec is not None:
        return "bulk"
    if spec.instance_selector_spec is not None:
        return "instance_selector"
    return None


def restore_raised_schema(exc: Exception, response: Response) -> Response:
    """Put an ``AdditionalInputRequired`` schema back into the body as it was raised.

    The mapped exception's ``detail`` is DRF's, every leaf an ``ErrorDetail``
    string, because that is what the configured ``EXCEPTION_HANDLER`` walks; the
    schema itself rides on its ``schema`` attribute. Called with the response
    that handler built, so the handler sees what it always saw, and the client
    still gets JSON Schema rather than ``"default": "False"``. Any other
    exception, and any response without a ``schema`` key of its own, comes back
    as it was.

    Called from two places, which between them cover every route drfs ships to a
    mapped ``ServiceError``: ``_ServesRaisedSchema`` below, for drfs' views and
    viewset bases, and the exception handler ``@service_action`` hands
    ``APIView.handle_exception`` on whatever viewset declares it. Where both run,
    the second writes what the first wrote, so the body is the same. A handler
    that declines the error answers ``None``, which comes back as ``None`` for
    DRF to raise; held by test_a_handler_declining_the_error_runs_once_on_any_viewset.
    """
    # Typed ``Response`` as DRF's stubs type it, but a configured
    # ``EXCEPTION_HANDLER`` may answer with any Django response, which DRF
    # serves as it is; only DRF's ``Response`` has a ``.data``.
    data: Any = getattr(response, "data", None)
    # Each condition is held by its own test in
    # tests/views/test_additional_input_required_over_http.py:
    # the exception type by test_another_error_naming_a_schema_field_is_left_alone,
    # the dict by test_a_handler_answering_with_a_string_body_is_left_alone (a
    # ``str`` body saying "schema", which ``in`` matches as a substring, so a
    # weaker ``data is not None`` spreads it and raises), and the key by
    # test_a_handler_reading_every_leafs_code_answers_with_its_own_body. A body
    # of ``None``, or no ``.data`` at all, is held by
    # test_a_handler_that_answers_with_no_body_is_left_alone and
    # test_a_handler_answering_with_a_django_response_is_left_alone.
    if (
        isinstance(exc, _AdditionalInputAPIException)
        and isinstance(data, dict)
        and "schema" in data
    ):
        # A new dict rather than an assignment into the old one: under DRF's
        # default handler ``response.data`` *is* ``exc.detail``, and the
        # exception should keep describing itself the DRF way. Held by
        # test_the_exception_keeps_drfs_shape_after_the_body_is_restored.
        response.data = {**data, "schema": exc.schema}
    return response


class _ServesRaisedSchema:
    """Runs ``restore_raised_schema`` over every response ``handle_exception`` builds.

    Inherited by ``MutationFlowMixin`` (the three mutation views and the
    viewset mixins) and ``_ActionSpecsMixin`` (every drfs viewset base,
    ``ActionSerializerResolver`` included), which between them are every class
    drfs ships that maps a ``ServiceError`` into a response. Defined once, so a
    class inheriting both runs it once.

    It runs only where it precedes DRF's view in the bases: in
    ``class V(GenericViewSet, ActionSerializerResolver)``, ``APIView``'s own
    ``handle_exception`` answers first and never calls this one. Nothing drfs
    ships is composed that way. A user who lists a drfs mixin after
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
