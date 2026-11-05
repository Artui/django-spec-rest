"""``spec_options`` - the OPTIONS answer of a route serving kernel specs, read off the specs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from django.core.exceptions import PermissionDenied
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.schema.spec_caller_input_schema import spec_caller_input_schema
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.metadata import SimpleMetadata
from rest_framework.request import Request, clone_request
from rest_framework.response import Response

from django_spec_rest.dispatch.kernel_edge import UNKNOWN_ARGUMENTS, judge_without_arguments
from django_spec_rest.views.utils import view_call_context, view_pool_seeds

# DRF's ``SimpleMetadata`` describes these two and no other method.
_DESCRIBED_METHODS = ("POST", "PUT")


def spec_options(
    view: Any, request: Request, served: Mapping[str, KernelServiceSpec | KernelSelectorSpec]
) -> Response:
    """Answer OPTIONS for ``view`` as DRF's ``APIView.options`` does, describing ``served``.

    ``served`` maps each method the route serves through a kernel spec to that
    spec. The answer keeps DRF's shape: ``name``, ``description``,
    ``renders`` and ``parses`` exactly as DRF's ``SimpleMetadata`` reads them,
    and ``actions`` for a ``POST`` or ``PUT`` in ``served`` that the view
    allows. A view setting ``metadata_class = None`` refuses OPTIONS, as DRF's
    does (test_options_metadata's test_a_view_without_a_metadata_class_refuses_options).

    Nothing of the spec runs. DRF's own metadata probes ``get_object()`` for a
    ``PUT`` and ``get_serializer()`` for each method, which runs the target
    selector and needs a ``serializer_class`` a spec-only view does not have;
    here no selector, provider, service, precondition or affordance condition
    is asked, and ``initial()`` has run authentication, permissions and
    throttles before this is called, as for every handler.

    A method is described only when the caller may send it: DRF's per-method
    ``check_permissions`` on a clone of the request carrying that method, as
    DRF's metadata asks it, and then the spec's checks judged on no
    arguments, as the edge judges a write whose body fails its shape
    (``judge_without_arguments``), with the view's call context and the pool
    seeds the edge dispatches with, the view's ``pool_seeds`` (test_pool_seeds'
    test_options_asks_a_check_naming_a_seed_with_the_view_s_seeds). So a
    method left out here is one whose write the edge refuses whatever the
    body, and one described is one whose write tells the caller what its
    body lacks (test_a_refused_caller_whatever_the_body's
    test_options_hides_a_method_exactly_when_its_write_is_refused_first).
    Either refusing leaves the method out of ``actions``, never the answer
    a 403: OPTIONS describes, and the method is still routed.

    The description is the kernel's ``spec_caller_input_schema``, what a
    caller is asked to send: ``spec.parameters()`` less what the server fills
    (the view's seeds, test_options_metadata's
    test_a_read_named_for_a_seed_the_view_registers_is_not_described, and every
    key a typed provider fills), a key a provider may
    fill offered and not required, a ``partial`` spec's fields required
    nowhere, and a ``many`` spec's rows read the same way by what its
    ``input_data`` reaches. Less, then, what stays this transport's: the
    route's own captures, which the edge reads from the URL over anything the
    body sends, and the target selector's reads, which the edge never reads
    from the body. It is built under the edge's unknown-argument policy, so
    under ``IGNORE`` it states no ``additionalProperties``.
    """
    if view.metadata_class is None:
        return view.http_method_not_allowed(request)
    return Response(
        _SpecMetadata(served).determine_metadata(request, view), status=status.HTTP_200_OK
    )


class _SpecMetadata(SimpleMetadata):
    """DRF's ``SimpleMetadata`` with ``actions`` read off the specs a route serves."""

    def __init__(self, served: Mapping[str, KernelServiceSpec | KernelSelectorSpec]) -> None:
        self.served = served

    def determine_actions(self, request: Request, view: Any) -> dict[str, Any]:
        # Built here, from the OPTIONS request itself, before a clone carrying
        # a described method is swapped onto the view: the context is kept on
        # the view once built, so built inside the swap it would name the
        # first clone's method for every method after it
        # (test_spec_options' test_authorize_is_asked_with_the_views_call_context).
        call_context = view_call_context(view, request)
        allowed = set(view.allowed_methods)
        actions: dict[str, Any] = {}
        for method in _DESCRIBED_METHODS:
            spec = self.served.get(method)
            # One arc to coverage, so each condition is named: a method the
            # view allows that no kernel spec serves by test_options_metadata's
            # test_allow_keeps_a_views_own_handler_without_a_spec, and a
            # method the view does not allow by
            # test_a_method_the_view_does_not_allow_is_not_described.
            if spec is None or method not in allowed:
                continue
            if not _grants(view, request, method, spec, call_context):
                continue
            try:
                asked = spec_caller_input_schema(
                    spec, pool_seeds=view_pool_seeds(view), unknown_arguments=UNKNOWN_ARGUMENTS
                )
            except (AttributeError, KeyError, TypeError):
                # A Validator whose serializer cannot be built without the
                # call's context (a ``get_fields`` reading a key the view's
                # input layers add) is described outside any call, with DRF's
                # context of no view and no request, and raises one of the
                # three ``describe_serializer`` reads the same way. The real
                # call builds it with that context, so the method stays
                # routed and is left out here, where DRF's own metadata ended
                # in a 500 (test_options_metadata's
                # test_a_context_dependent_input_is_left_out_rather_than_a_500).
                continue
            actions[method] = _described(spec, asked, view)
        return actions


def _grants(
    view: Any,
    request: Request,
    method: str,
    spec: KernelServiceSpec | KernelSelectorSpec,
    call_context: dict[str, Any],
) -> bool:
    """Whether the caller may send ``method``: the view's own check, then the edge's judgment of the spec."""
    view.request = clone_request(request, method)
    try:
        view.check_permissions(view.request)
        judge_without_arguments(
            spec,
            principal=request.user,
            call_context=call_context,
            pool_seeds=view_pool_seeds(view),
        )
    except (APIException, PermissionDenied, NotPermitted, PrincipalUnavailable):
        return False
    finally:
        view.request = request
    return True


def _described(
    spec: KernelServiceSpec | KernelSelectorSpec, asked: dict[str, Any], view: Any
) -> dict[str, Any]:
    """The JSON Schema of what the caller sends ``spec``: the kernel's ``asked`` less this transport's.

    ``asked`` is ``spec_caller_input_schema``'s, which leaves out what the
    server fills (``server_owned_keys``) and requires nothing a provider may
    fill (test_options_metadata's
    test_a_read_a_provider_may_decline_is_offered_and_not_required), nor a
    ``partial`` spec's fields (test_a_partial_spec_s_put_requires_none_of_its_fields).
    Left out here: the route's own captures, which the edge reads from the
    URL over the body (test_a_route_capture_is_not_described_as_input), and
    the target lookup's parameters, which the edge takes from the route and
    the query string and drops from the body whatever the method, an
    update's (test_a_put_s_target_reads_are_not_described_as_input) as a
    POST's acting on a row (test_a_post_s_target_reads_are_not_described).
    The lookup's ``parameters()``, as the edge drops them, which for a
    target are its reads, its filters among them: a nested selector may
    declare no shapes. A ``many`` spec keeps its list as the one property,
    its rows inside it.
    """
    dropped = set(view.kwargs)
    target = spec.target_selector_spec() if isinstance(spec, KernelServiceSpec) else None
    # A ``many`` update has no target, so nothing to leave out
    # (test_a_bulk_put_with_no_target_is_described).
    if target is not None:
        dropped |= target.parameters().names()
    return _without(asked, dropped)


def _without(schema: dict[str, Any], names: Iterable[str]) -> dict[str, Any]:
    """``schema`` with ``names`` neither offered nor required, an empty ``required`` dropped.

    The same few lines as ``ServiceAutoSchema``'s own: the two transports
    share no module both may import, and ``openapi/`` is opt-in, so this
    module never imports it.
    """
    dropped = frozenset(names)
    kept = {key: value for key, value in schema.items() if key != "required"}
    kept["properties"] = {
        name: fragment for name, fragment in schema["properties"].items() if name not in dropped
    }
    required = [name for name in schema.get("required", ()) if name not in dropped]
    if required:
        kept["required"] = required
    return kept
