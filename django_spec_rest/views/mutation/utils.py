"""Helpers used by the mutation views, viewset mixins, and ``@service_action``.

The HTTP half either side of ``dispatch_spec`` — view hooks in, response out.
There is deliberately **no** flow runner here: the mutation pipeline lives in
``dispatch_spec``, and a behaviour that belongs to the *spec* belongs in the
core, or it will be honoured on one transport and not the other.

``map_service_error`` is re-imported from its own leaf module rather than
defined here, so ``call_service`` can map errors without importing this one.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from dataclasses import is_dataclass
from typing import Any, Literal, cast

from django.db.models import Model
from django_service_specs.dispatch.present import present
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from rest_framework import status as drf_status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer, Serializer
from rest_framework_dataclasses.serializers import DataclassSerializer

from django_spec_rest.dispatch.apply_input_data import apply_input_data
from django_spec_rest.dispatch.dispatch_spec import dispatch_spec
from django_spec_rest.dispatch.kernel_edge import (
    answering_refusals,
    dispatch_kernel_spec,
    runs_on_kernel,
)
from django_spec_rest.dispatch.render_spec_output import render_spec_output
from django_spec_rest.dispatch.renderable_serializer_class import renderable_serializer_class
from django_spec_rest.exceptions.service_error import ServiceError
from django_spec_rest.selectors.utils import (
    check_view_object_permissions,
)
from django_spec_rest.service_specs.kernel_spec_variant import kernel_spec_variant
from django_spec_rest.types.dispatch_result import DispatchResult
from django_spec_rest.types.service_spec import ServiceSpec
from django_spec_rest.types.unset import UNSET
from django_spec_rest.views.mutation.apply_response_finalizer import (
    apply_response_finalizer,
)
from django_spec_rest.views.mutation.map_service_error import (
    _AdditionalInputAPIException,
    map_service_error,
)
from django_spec_rest.views.mutation.resolve_success_status import resolve_success_status
from django_spec_rest.views.utils import (
    add_affordances,
    get_class_attr,
    resolve_serializer_context,
    resolve_view_hooks,
    view_call_context,
)


def build_input_serializer(
    request: Request,
    input_serializer: type | None,
    *,
    partial: bool = False,
    extra_data: Mapping[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    instance: Any = None,
    many: bool = False,
) -> Serializer | None:
    """Construct + validate the bound input serializer; ``None`` if absent.

    The serializer is returned validated (``is_valid(raise_exception=True)`` has
    run) but never saved; the service owns persistence.

    Args:
        request: The request whose ``data`` is validated.
        input_serializer: A bare dataclass type (wrapped in a
            ``DataclassSerializer`` on the fly), a ``DataclassSerializer``
            subclass, or any other ``Serializer`` subclass such as
            ``ModelSerializer``. The first two produce a dataclass instance as
            ``validated_data``, the third a ``dict``.
        partial: Validate partially, as DRF's ``serializer(partial=…)``.
        extra_data: Merged on top of ``request.data`` before the serializer is
            constructed, server-provided keys winning on overlap — the seam the
            ``input_data`` resolver chain uses to lift URL kwargs into serializer
            input. The merge goes through
            ``apply_input_data``,
            which keeps a form-encoded / multipart ``QueryDict``'s scalars from
            flattening into one-element lists.
        context: Forwarded to the serializer's ``context=`` so DRF-style
            ``self.context["request"]`` / ``["view"]`` lookups work inside
            validators and fields.
        instance: The resolved mutation target on update / destroy flows. The
            serializer is constructed DRF-style, so ``self.instance`` is
            populated inside ``validate()`` / field validators and
            instance-aware validators (``UniqueValidator`` excluding the current
            row) behave as under DRF's own update flow.
        many: Validate ``data`` as a list — the bulk list-payload path;
            ``validated_data`` is then a list of items.
    """
    if input_serializer is None:
        return None
    if extra_data:
        data: Any = apply_input_data(request.data, extra_data)
    else:
        data = request.data
    return build_input_serializer_from_data(
        data,
        input_serializer,
        partial=partial,
        context=context,
        instance=instance,
        many=many,
    )


def build_input_serializer_from_data(
    data: Any,
    input_serializer: type | None,
    *,
    partial: bool = False,
    context: dict[str, Any] | None = None,
    instance: Any = None,
    many: bool = False,
) -> Serializer | None:
    """Construct + validate the bound input serializer from a raw ``data`` dict.

    The transport-neutral core of
    [`build_input_serializer`][django_spec_rest.views.mutation.utils.build_input_serializer]:
    it takes the input ``data`` directly instead of reaching into a DRF
    ``request.data``, so a non-HTTP caller (``dispatch_spec``) and the HTTP view path
    share one validation implementation. See
    [`build_input_serializer`][django_spec_rest.views.mutation.utils.build_input_serializer]
    for the remaining parameter semantics."""
    if input_serializer is None:
        return None
    serializer_kwargs: dict[str, Any] = {"data": data, "partial": partial}
    if many:
        serializer_kwargs["many"] = True
    if instance is not None:
        serializer_kwargs["instance"] = instance
    if context is not None:
        serializer_kwargs["context"] = context
    if isinstance(input_serializer, type) and issubclass(input_serializer, Serializer):
        serializer: Serializer = input_serializer(**serializer_kwargs)
    elif is_dataclass(input_serializer):
        serializer = DataclassSerializer(
            dataclass=input_serializer,
            **serializer_kwargs,
        )
    else:
        raise TypeError(
            "input_serializer must be a dataclass type or a Serializer subclass; "
            f"got {input_serializer!r}."
        )
    serializer.is_valid(raise_exception=True)
    return serializer


def validate_input(
    request: Request,
    input_serializer: type | None,
    *,
    partial: bool = False,
    extra_data: Mapping[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    instance: Any = None,
) -> Any:
    """Validate ``request.data`` against ``input_serializer``; ``None`` if absent.

    Thin wrapper over
    [`build_input_serializer`][django_spec_rest.views.mutation.utils.build_input_serializer]
    (see there for the parameter semantics) returning only ``validated_data``, for
    callers that don't need the bound serializer itself."""
    serializer = build_input_serializer(
        request,
        input_serializer,
        partial=partial,
        extra_data=extra_data,
        context=context,
        instance=instance,
    )
    return None if serializer is None else serializer.validated_data


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


def render_mutation_response(
    view: Any,
    request: Request,
    spec: ServiceSpec[Any, Any, Any],
    result: DispatchResult,
    *,
    instance: Any,
    default_status: int,
    render_instance_on_none: bool,
    output_context: Callable[[Any], dict[str, Any]],
) -> Response:
    """Turn a
    [`DispatchResult`][django_spec_rest.types.dispatch_result.DispatchResult]
    into the HTTP ``Response`` for a mutation.

    Everything downstream of the dispatch that is genuinely transport-shaped, and
    nothing that isn't: resolve the success status against the *action's* default
    (201 create / 200 update / 204 destroy), which the core cannot know, and
    answer a value under ``200`` wherever that status is ``204``, because a
    ``204`` carries no body; fall
    back to the in-memory ``instance`` when an in-place update returned ``None``;
    render a value through the output serializer, or emit a body-less response
    when there is no value to render, whether or not a serializer is declared;
    apply ``spec.response_finalizer`` (2xx, pre-render).

    ``render_instance_on_none`` is the caller's update-vs-destroy intent — read
    it as "the target still exists". Deliberately **not** a spec field and **not**
    transport-neutral: off HTTP the equivalent is ``output_selector_spec``.
    """
    value: Any = result.value
    selector_ran: bool = (
        spec.output_selector_spec is not None and spec.output_selector_spec.selector is not None
    )
    output_serializer: type[BaseSerializer[Any]] | None = renderable_serializer_class(
        spec.output_selector_spec.output_serializer
        if spec.output_selector_spec is not None
        else None
    )

    if (
        value is None
        and instance is not None
        and render_instance_on_none
        and output_serializer is not None
        and not selector_ran
    ):
        # Update-in-place that returned nothing — render the in-memory instance,
        # mirroring DRF's ``UpdateAPIView``. Gated on the caller's intent rather
        # than the status code, so destroy never surfaces a stale post-delete row
        # even under a custom success status; and a selector that already ran
        # owns its ``None``.
        value = instance

    status_pool: dict[str, Any] = {
        "request": request,
        "view": view,
        "result": result.service_result,
    }
    if instance is not None:
        status_pool["instance"] = instance
    resolved_status: int = resolve_success_status(
        spec.success_status, default=default_status, pool=status_pool
    )
    # Empty-body responses fall back to 204 when ``success_status`` is unset; a
    # set int/callable applies uniformly.
    resolved_empty_status: int = (
        drf_status.HTTP_204_NO_CONTENT if spec.success_status is None else resolved_status
    )
    # And the converse: a body never goes out under a ``204``. A destroy whose
    # service returns something to present (a soft delete returning its row, a
    # count) answers ``200``, as the bulk path does for the same reason.
    resolved_body_status: int = status_for_a_body(resolved_status)

    # Whether there is a value comes before how to render one. A serializer over
    # ``None`` builds a row of blank and default field values for no row, which
    # is what a create, a re-read finding nothing and a destroy all answered with
    # once the nested spec declared an ``output_serializer``. ``None`` here is
    # what is left after the update fallback above, so an update that mutated in
    # place still renders its target.
    if value is None:
        if selector_ran:
            # A selector that returned ``None`` is an authoritative no-content result.
            response = Response(status=drf_status.HTTP_204_NO_CONTENT)
        else:
            response = Response(status=resolved_empty_status)
    elif output_serializer is not None:
        rendered: Any = output_serializer(value, context=output_context(value)).data
        response = Response(
            add_affordances(spec, rendered, value, many=False), status=resolved_body_status
        )
    else:
        response = Response(value, status=resolved_body_status)

    return apply_response_finalizer(
        spec.response_finalizer,
        response,
        request=request,
        view=view,
        result=result.service_result,
        instance=instance,
        data=result.data,
    )


def _dispatch_bulk_via_spec(
    view: Any,
    request: Request,
    spec: ServiceSpec[Any, Any, Any],
    *,
    default_status: int,
) -> Response:
    """Render a bulk (``many`` / collection) spec through ``dispatch_spec``.

    The list body / collection target, validation, and per-set scoping all live in the
    transport-neutral path; here we only map its
    [`DispatchResult`][django_spec_rest.types.dispatch_result.DispatchResult] to
    a DRF ``Response`` and translate a ``ServiceError`` the same way the single-instance
    flow does. The status and finalizer pools carry no ``instance`` / ``data`` on a bulk
    path.

    The two request channels stay apart here as they do on the single-instance path —
    the body validates, the query string filters — and the target guard is passed for
    the same reason it is there: whatever the collection selector resolved is what the
    service is about to mutate."""

    if spec.many:
        # ``many`` is a list body straight through.
        params: Any = request.data
    else:
        # Collection target: the body payload under the view's URL kwargs. Route
        # captures go last because they are authoritative — a client-supplied
        # value must not override the route scope.
        body = request.data if isinstance(request.data, dict) else {}
        url_kwargs = getattr(view, "kwargs", None) or {}
        params = {**body, **url_kwargs}

    view_hooks = resolve_view_hooks(view, request)
    # The request's one dict, for the edge and the renderer alike; each hand-off
    # is held by test_a_bulk_create_hands_every_provider_the_request_s_context.
    call_context = view_call_context(view, request)
    try:
        result = dispatch_spec(
            spec,
            user=getattr(request, "user", None),
            params=params,
            # The same channel split the single-instance path applies: the body
            # validates and the query string filters. The ``QueryDict`` itself
            # goes through rather than a flattened copy, so a repeated parameter
            # still reaches a multi-valued filter as all of its values.
            filter_data=request.query_params,
            request=request,
            view=view,
            view_hooks=view_hooks,
            on_target_resolved=check_view_object_permissions,
            call_context=call_context,
        )
    except ServiceError as exc:
        raise map_service_error(exc) from exc

    status_pool: dict[str, Any] = {"request": request, "view": view, "result": result.value}
    status = resolve_success_status(spec.success_status, default=default_status, pool=status_pool)
    if result.value is None:
        response = Response(status=status)
    else:
        payload = render_spec_output(
            spec,
            result.value,
            many=(result.kind == "list"),
            view=view,
            request=request,
            extras={"result": result.value},
            view_hooks=view_hooks,
            call_context=call_context,
        )
        response = Response(payload, status=status_for_a_body(status))

    return apply_response_finalizer(
        spec.response_finalizer,
        response,
        request=request,
        view=view,
        result=result.value,
    )


def dispatch_mutation_for_spec(
    view: Any,
    request: Request,
    spec: ServiceSpec[Any, Any, Any],
    *,
    instance: Any,
    default_status: int,
    render_instance_on_none: bool,
    partial: bool = False,
) -> Response:
    """End-to-end dispatch for one ``ServiceSpec`` call over HTTP.

    Used by
    [`MutationFlowMixin`][django_spec_rest.views.mutation.mutation_flow_mixin.MutationFlowMixin],
    the standalone mutation views, and ``@service_action`` so the call shape lives in
    one place: resolve the view's hook chains (``resolve_view_hooks``), dispatch through
    [`dispatch_spec`][django_spec_rest.dispatch.dispatch_spec.dispatch_spec],
    render (``render_mutation_response``). Only the first and last steps are HTTP's. The
    target is passed in rather than resolved in the core, because HTTP's
    ``get_object()`` chain has no off-HTTP meaning; a bulk spec takes the same route
    with its own params assembly and renderer.

    ``partial`` is the transport-derived flag (PATCH → ``True``) and
    ``spec.partial`` overrides it when set. Being the single call-shape point,
    the override is honoured uniformly across every surface — including create
    dispatch, so a create spec with ``partial=True`` validates partially. The
    flag reaches ``dispatch_spec`` as its ``partial=`` beside the declared spec,
    never on a copy of the spec, which the edge would compile afresh on every
    request. A ``PATCH`` to an input that cannot take a partial call (a
    dataclass) is validated whole, as a ``PUT`` is.

    **A kernel spec parts from the drfs path here**, at ``runs_on_kernel``,
    before anything reads a drfs-only field: it runs through the kernel's own
    ``dispatch`` (``dispatch_kernel_spec``) with the request's one dict as its
    ``call_context``, and its answer is presented by the spec's own presenter,
    through the kernel's ``present``. A body answers ``default_status``, or
    ``200`` where that is ``204``; nothing to present answers ``204``.
    """

    if runs_on_kernel(spec):
        return _dispatch_kernel_mutation(
            view,
            request,
            cast(KernelServiceSpec, spec),
            instance=instance,
            default_status=default_status,
            render_instance_on_none=render_instance_on_none,
            partial=partial,
        )

    if spec.partial is not None:
        partial = spec.partial
    elif partial:
        partial = _takes_a_partial_call(spec)
    if mutation_target_source(spec) == "bulk":
        return _dispatch_bulk_via_spec(view, request, spec, default_status=default_status)

    # ``instance`` may be UNSET ("the core resolves it"); the view-side
    # providers and the renderer only ever see a real target or ``None``.
    resolved: Any = None if instance is UNSET else instance
    view_hooks = resolve_view_hooks(view, request, instance=resolved)

    try:
        result = dispatch_spec(
            spec,
            user=getattr(request, "user", None),
            params=request.data,
            filter_data=request.query_params,
            request=request,
            view=view,
            instance=instance,
            view_hooks=view_hooks,
            on_target_resolved=check_view_object_permissions,
            partial=partial,
            # The request's one dict, which the output context below hands its
            # providers too (test_a_create_hands_every_provider_the_request_s_context).
            call_context=view_call_context(view, request),
        )
    except ServiceError as exc:
        raise map_service_error(exc) from exc

    if result.kind == "not_found":
        # Off HTTP a matchless ``instance_selector_spec`` is a neutral
        # ``not_found`` for the transport to map; here it is DRF's 404. The
        # nested spec's ``allow_none`` stays ignored — it expresses a nullable
        # *read* contract, and a mutation against a missing row is always a 404.
        raise NotFound()

    def output_context(value: Any) -> dict[str, Any]:
        # Resolved lazily with the final value so the output context provider can
        # run a single batched query against the exact instance being serialized.
        # Uses the four-layer resolver rather than the ``ViewHooks`` carrier: the
        # carrier exists to cross the boundary *into* the dispatch core, and
        # rendering never crosses it.
        return resolve_serializer_context(
            view,
            request,
            direction_hook="get_output_serializer_context",
            action_hook=f"get_{getattr(view, 'action', None)}_output_serializer_context"
            if getattr(view, "action", None)
            else None,
            spec_provider=(
                spec.output_selector_spec.output_serializer_context
                if spec.output_selector_spec is not None
                else None
            ),
            extras={"result": value},
        )

    return render_mutation_response(
        view,
        request,
        spec,
        result,
        instance=result.instance,
        default_status=default_status,
        render_instance_on_none=render_instance_on_none,
        output_context=output_context,
    )


def _dispatch_kernel_mutation(
    view: Any,
    request: Request,
    spec: KernelServiceSpec,
    *,
    instance: Any,
    default_status: int,
    render_instance_on_none: bool,
    partial: bool,
) -> Response:
    """``dispatch_mutation_for_spec`` for a kernel spec: the kernel's ``dispatch``, then DRF's response.

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
      a ``PUT`` too; a spec cannot force a ``PATCH`` whole, as a drfs spec's
      ``partial=False`` did. A Validator that cannot take a partial call (a
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


def _takes_a_partial_call(spec: ServiceSpec[Any, Any, Any]) -> bool:
    """Whether a request's ``partial`` flag can reach ``spec``'s input as one.

    A ``PATCH`` asks for a partial call, and the compiled Validator says whether
    it can take one: a dataclass input is built from every field, so it cannot,
    and the kernel refuses a partial spec over it when it is built. The request
    did not declare anything, so its flag is dropped there, and the ``PATCH`` is
    validated whole, a field it leaves out answering ``400``. The spec's own
    ``partial`` is never read through here: one declared over a dataclass is the
    author's, and refused as theirs.

    One arc to coverage, so each operand is named: without the first, a
    ``PATCH`` to a spec with no input (``test_partial_update_key_wins_over_update_for_patch``)
    reads an attribute off ``None``; without the second,
    ``test_a_patch_over_a_dataclass_input_validates_every_field`` is refused as
    a misconfigured spec.
    """
    # A drfs ``ServiceSpec`` compiles to the kernel's.
    validator = cast(KernelServiceSpec, kernel_spec(spec)).validator
    return validator is None or validator.supports_partial


def resolve_mutation_instance(
    view: Any,
    spec: ServiceSpec[Any, Any, Any],
) -> Any:
    """Resolve the mutation target, or defer to the core.

    A kernel spec's target is its own target selector's, or none: the view's
    ``get_object()`` is never asked for one.

    Returns: ``None`` for a **bulk** spec (``many=True`` or a
        ``collection_selector_spec``): there is no single instance, and the
        ``get_object()`` lookup would 404 a body-only bulk endpoint. ``UNSET`` when the
        spec carries an ``instance_selector_spec`` — *the core resolves it*, with the
        right kwarg pool, error label, and reserved-seed strip. Object permissions still
        run: the core fires ``on_target_resolved`` against the resolved target and the
        HTTP caller passes ``check_view_object_permissions``. Otherwise the view's
        ``get_object()`` chain (an ``action_specs["retrieve"]`` selector via
        [`SelectorRetrieveMixin`][django_spec_rest.viewsets.selector_retrieve_mixin.SelectorRetrieveMixin],
        else DRF's ``queryset`` / ``lookup_field`` lookup, else a user override) — the
        one branch that is genuinely HTTP-only and so cannot move.

    **``filter_backends`` do not apply to the two spec-driven branches.** DRF
    runs ``filter_queryset()`` inside its own ``get_object()``, so an
    ``instance_selector_spec`` (resolved by the core) and a retrieve selector
    (which overrides ``get_object()``) both bypass it, exactly as a hand-written
    ``get_object()`` override does. A tenant-scoping backend in
    ``DEFAULT_FILTER_BACKENDS`` therefore does not narrow the row a PATCH or
    DELETE may reach here, while the sibling list action stays scoped. Put the
    scoping in the selector's own queryset. Only the last branch — DRF's own
    ``get_object()`` — applies the backends.
    """
    source = mutation_target_source(spec)
    if source == "bulk":
        return None
    if source == "instance_selector":
        return UNSET
    # The kernel takes a target only where the spec declares the selector that
    # would find it, and refuses one handed to a spec declaring none, so a
    # kernel spec's target is its own lookup's or there is none: the view's
    # ``get_object()`` never runs for it, and the call acts on no row
    # (test_service_update_view's test_a_spec_with_no_target_selector_acts_on_no_row).
    if runs_on_kernel(spec):
        return None
    return view.get_object()


def mutation_target_source(
    spec: ServiceSpec[Any, Any, Any],
) -> Literal["bulk", "instance_selector", "get_object"]:
    """Where a mutation's target comes from, as
    [`resolve_mutation_instance`][django_spec_rest.views.mutation.utils.resolve_mutation_instance]
    decides it.

    Its own function so a caller that must not *perform* the lookup can still
    ask which one applies: DRF's OPTIONS metadata calls ``get_object()`` as an
    object-permission probe for every PUT it describes, and has to know when a
    real PUT would never have called it.

    Each condition is held by a test that fails without it: ``spec.many`` by the
    ``put-bulk-no-queryset`` row of test_options_describes_every_spec_only_shape,
    ``collection_selector_spec`` by
    TestBulkDeleteCollection.test_delete_over_query_filter_204, and the instance
    selector's ``selector`` by
    test_selectorless_instance_spec_falls_back_to_get_object.
    """
    if spec.many or spec.collection_selector_spec is not None:
        return "bulk"
    instance_spec = spec.instance_selector_spec
    if instance_spec is not None and instance_spec.selector is not None:
        return "instance_selector"
    return "get_object"


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
    # Each condition is held by its own test in tests/test_additional_input_required.py:
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
    Held by test_a_mixin_listed_after_generic_viewset_serves_its_own_actions_stringified
    and test_service_action_serves_the_schema_as_raised_on_any_viewset.
    """

    def handle_exception(self, exc: Exception) -> Response:
        return restore_raised_schema(
            exc,
            super().handle_exception(exc),  # ty: ignore[unresolved-attribute]
        )
