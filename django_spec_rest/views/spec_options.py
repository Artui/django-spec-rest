"""``spec_options`` - the OPTIONS answer of a route serving kernel specs, read off the specs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import PermissionDenied
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.dispatch.authorize import authorize
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.schema.parameters_schema import parameters_schema
from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.server_owned_keys import server_owned_keys
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.metadata import SimpleMetadata
from rest_framework.request import Request, clone_request
from rest_framework.response import Response

from django_spec_rest.dispatch.kernel_edge import UNKNOWN_ARGUMENTS
from django_spec_rest.views.utils import view_call_context

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
    does (test_spec_options' test_a_view_without_a_metadata_class_refuses_options).

    Nothing of the spec runs. DRF's own metadata probes ``get_object()`` for a
    ``PUT`` and ``get_serializer()`` for each method, which runs the target
    selector and needs a ``serializer_class`` a spec-only view does not have;
    here no selector, provider, service, precondition or affordance condition
    is asked, and ``initial()`` has run authentication, permissions and
    throttles before this is called, as for every handler.

    A method is described only when the caller may send it: DRF's per-method
    ``check_permissions`` on a clone of the request carrying that method, as
    DRF's metadata asks it, and then the kernel's ``authorize`` for the spec,
    with the view's call context and the pool seeds the edge dispatches with.
    Either refusing leaves the method out of ``actions``, never the answer
    a 403: OPTIONS describes, and the method is still routed.

    The description is ``parameters_schema`` over ``spec.parameters()`` less
    what the server fills for the call: ``server_owned_keys`` (the seeds and
    every key a typed provider fills) and the route's own captures, which the
    edge reads from the URL over anything the body sends. It is built under
    the edge's unknown-argument policy, so under ``IGNORE`` it states no
    ``additionalProperties``.
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
            # One arc to coverage, so each condition is named: a method no
            # spec serves by every route of test_every_route_answers_options_from_its_spec
            # (the create view serves no PUT), and a method the view does not
            # allow by test_a_method_the_view_does_not_allow_is_not_described.
            if spec is None or method not in allowed:
                continue
            if not _grants(view, request, method, spec, call_context):
                continue
            try:
                actions[method] = _described(spec, view)
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
        return actions


def _grants(
    view: Any,
    request: Request,
    method: str,
    spec: KernelServiceSpec | KernelSelectorSpec,
    call_context: dict[str, Any],
) -> bool:
    """Whether the caller may send ``method``: the view's own check, then the spec's ``authorize``."""
    view.request = clone_request(request, method)
    try:
        view.check_permissions(view.request)
        authorize(spec, request.user, call_context=call_context, pool_seeds=DEFAULT_POOL_SEEDS)
    except (APIException, PermissionDenied, NotPermitted, PrincipalUnavailable):
        return False
    finally:
        view.request = request
    return True


def _described(spec: KernelServiceSpec | KernelSelectorSpec, view: Any) -> dict[str, Any]:
    """The JSON Schema of what the caller sends ``spec`` on this route."""
    owned = server_owned_keys(spec, pool_seeds=DEFAULT_POOL_SEEDS) | set(view.kwargs)
    sent = Parameters.of(*(param for param in spec.parameters() if param.name not in owned))
    return parameters_schema(sent, unknown_arguments=UNKNOWN_ARGUMENTS)
