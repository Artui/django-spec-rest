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
from collections.abc import Callable
from typing import Any, Literal

from django.core.exceptions import ImproperlyConfigured, SuspiciousOperation
from django.db.models import Model
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
    variant: str | None = None,
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
      The status is the view's ``success_status`` for the action it serves
      over ``default_status``, a body never going out under ``204``; then
      the view's ``response_finalizer`` for that action (``action_answer``,
      ``MutationFlowMixin``). ``variant`` is the key a ``DiscriminatedAction``
      chose, offered to both only there, or ``None`` on any plain spec.
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
        view_hooks=_view_hooks(view, request, spec, instance=resolved),
        on_target=lambda found: _object_permissions(view, request, found),
        pool_seeds=view_pool_seeds(view),
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
    success_status = action_answer(view, "success_status")
    pool: dict[str, Any] = {"request": request, "view": view, "result": result.service_result}
    if result.instance is not None:
        pool["instance"] = result.instance
    if variant is not None:
        pool["variant"] = variant
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
    """The view's hook chains for this call, a failed read of the body judged where a hook made it.

    The hooks run before the edge, since what they answer is shown to the
    spec's checks (test_a_hook_runs_before_the_checks_and_its_value_is_shown_to_them),
    so the edge's own judgment of an unreadable body (``_is_form_body``) comes too
    late for a read one of them makes. So that read is judged here, on no
    arguments, and a caller the checks refuse is told that, whatever it sent
    (test_a_refused_caller_is_refused_where_a_view_hook_reads_the_body_first). An
    admitted caller is told what the read raised, the same exception.

    Only on the failure. The body is not read ahead of the hooks, where a hook
    reading the raw bytes of a multipart request would find them gone
    (test_a_hook_may_read_the_raw_body_of_a_multipart_request), and a hook's other
    exceptions leave as they did, unjudged
    (test_a_hook_s_own_refusal_is_answered_before_the_checks_as_before). Told apart
    by class, so a hook raising ``ParseError`` itself is judged as a read that did
    (test_a_hook_raising_what_a_read_raises_is_judged_like_a_read). ``spec`` is the
    view's declaration, the one OPTIONS asks of and a denial is compared with
    (``_check_denied``), since no twin of it is built until the edge runs.
    """
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
) -> Response:
    """Serve one request of a ``DiscriminatedAction``: refuse, choose, then run the chosen variant.

    DRF's ``initial()`` has asked the view's own classes. A caller every variant
    refuses stops here (``_refuse_a_caller_every_variant_refuses``), so it never
    reaches the body or the discriminator, and OPTIONS shows it nothing. The
    discriminator then chooses (``_chosen_key``) and the chosen variant runs
    through ``dispatch_mutation_for_spec`` as a plain entry does, its own checks
    deciding: its class-level check is asked twice, the cost of the first step
    (test_discriminated_action's
    test_the_chosen_variant_s_class_level_check_is_asked_twice_and_every_other_once).

    The row is the chosen variant's own target selector's
    (``resolve_mutation_instance``), and the keywords are
    ``dispatch_mutation_for_spec``'s.
    """
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
    """Raise the first variant's denial where every variant refuses the caller, the body unread.

    Each variant is judged on no arguments, as the OPTIONS answer judges it
    (``judge_without_arguments``), so a caller shown no variant there is told
    nothing here but its refusal, whatever it sends, unparseable JSON included.
    Every variant is asked, with no stop at the first that admits, so a check is
    asked the same number of times wherever its variant sits.

    The denial is raised with ``RefusedCall.spec`` set to the variant judged,
    never the wrapper, which compiles to nothing: ``_check_denied`` compares the
    denial's spec with it, and only then asks an anonymous caller to sign in
    rather than answering 403 (test_discriminated_action's
    test_an_anonymous_caller_every_variant_refuses_is_401_whatever_it_sends). A
    configuration error is no refusal and passes, as on a plain spec
    (test_a_misconfigured_variant_fails_rather_than_refuses).
    """
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
    """The key ``action``'s discriminator answers for this request, one of its ``specs``.

    Bound by the kernel's ``resolve_callable_kwargs``, so a ``call_context`` is
    handed by name alone and a catch-all never sees it
    (test_a_catch_all_is_handed_all_but_the_call_context). Inside the map, so a
    ``ServiceError`` it raises is answered as a service's is, and a DRF exception
    passes as raised; ``request.data`` is read there too, a body DRF cannot parse
    answering its own 400. An answer that is no key is the author's mistake, a
    500 naming the keys. One arc to coverage, so each conjunct is named by a
    case of test_a_stray_answer_is_improperly_configured_naming_the_keys: the
    ``str`` by ``["token"]``, which ``in`` raises ``TypeError`` over, and the key
    by ``"nope"``.
    """
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

    Called from two places, which between them cover every route the package
    ships to a mapped ``ServiceError``: ``_ServesRaisedSchema`` below, for its
    views and viewset bases, and the exception handler
    ``restore_schema_when_handled`` hands ``APIView.handle_exception`` for
    ``@service_action`` and ``@selector_action`` on whatever viewset declares
    them. Where both run,
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
        # test_the_exception_keeps_its_details_after_the_body_is_restored.
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
    """Have the exception handler this request's view runs put the raised schema back.

    Called by ``@service_action`` and ``@selector_action`` as the error leaves
    their handler. The restore is otherwise a ``handle_exception`` override on
    this package's bases, which a decorated method on DRF's own viewsets never
    reaches, and which DRF's own method shadows where one of them is listed
    after ``GenericViewSet``. A decorator owns no class, but it runs on the view
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
    test_service_action_serves_the_schema_as_raised_on_any_viewset and
    test_a_selector_action_serves_the_schema_as_raised_on_any_viewset, whose
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
