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
from django_spec_rest.types.discriminated_action import DiscriminatedAction
from django_spec_rest.views.utils import view_call_context, view_pool_seeds

# DRF's ``SimpleMetadata`` describes these two and no other method.
_DESCRIBED_METHODS = ("POST", "PUT")


def spec_options(
    view: Any,
    request: Request,
    served: Mapping[str, KernelServiceSpec | KernelSelectorSpec | DiscriminatedAction],
) -> Response:
    """Answer OPTIONS for ``view`` as DRF's ``APIView.options`` does, describing ``served``."""
    if view.metadata_class is None:
        return view.http_method_not_allowed(request)
    return Response(
        _SpecMetadata(served).determine_metadata(request, view), status=status.HTTP_200_OK
    )


class _SpecMetadata(SimpleMetadata):
    """DRF's ``SimpleMetadata`` with ``actions`` read off the specs a route serves."""

    def __init__(
        self, served: Mapping[str, KernelServiceSpec | KernelSelectorSpec | DiscriminatedAction]
    ) -> None:
        self.served = served

    def determine_actions(self, request: Request, view: Any) -> dict[str, Any]:
        # Built before the clone is swapped on: kept on the view, it would name the first method.
        call_context = view_call_context(view, request)
        allowed = set(view.allowed_methods)
        actions: dict[str, Any] = {}
        for method in _DESCRIBED_METHODS:
            spec = self.served.get(method)
            if spec is None or method not in allowed:
                continue
            described_as = {**call_context, "action": _dispatched_action(view, method)}
            described = (
                _variants_described(view, request, method, spec, described_as)
                if isinstance(spec, DiscriminatedAction)
                else _spec_described(view, request, method, spec, described_as)
            )
            if described is not None:
                actions[method] = described
        return actions


def _dispatched_action(view: Any, method: str) -> str | None:
    """The action ``method`` is dispatched under: the route's ``action_map`` entry, or ``None``."""
    return getattr(view, "action_map", {}).get(method.lower())


def _variants_described(
    view: Any,
    request: Request,
    method: str,
    action: DiscriminatedAction,
    call_context: dict[str, Any],
) -> dict[str, Any] | None:
    """``action``'s variants the caller may send, as ``{"anyOf": [...]}``, or ``None`` for none."""
    described = [
        schema
        for variant in action.specs.values()
        if (schema := _spec_described(view, request, method, variant, call_context)) is not None
    ]
    if not described:
        return None
    members: list[dict[str, Any]] = []
    for schema in described:
        if schema["properties"] and schema not in members:
            members.append(schema)
    return {"anyOf": members} if members else described[0]


def _spec_described(
    view: Any,
    request: Request,
    method: str,
    spec: KernelServiceSpec | KernelSelectorSpec,
    call_context: dict[str, Any],
) -> dict[str, Any] | None:
    """The JSON Schema of what the caller sends ``spec`` by ``method``, or ``None`` if refused."""
    if not _grants(view, request, method, spec, call_context):
        return None
    try:
        asked = spec_caller_input_schema(
            spec,
            pool_seeds=view_pool_seeds(view),
            unknown_arguments=UNKNOWN_ARGUMENTS,
            call_context=call_context,
        )
    except (AttributeError, KeyError, TypeError):
        return None
    return _described(spec, asked, view)


def _grants(
    view: Any,
    request: Request,
    method: str,
    spec: KernelServiceSpec | KernelSelectorSpec,
    call_context: dict[str, Any],
) -> bool:
    """Whether the caller may send ``method``: the view's check, then the edge's judgment."""
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
    """JSON Schema of the caller's ``spec`` body: the kernel's ``asked``, less this transport's."""
    dropped = set(view.kwargs)
    target = spec.target_selector_spec() if isinstance(spec, KernelServiceSpec) else None
    if target is not None:
        dropped |= target.parameters().names()
    return _without(asked, dropped)


def _without(schema: dict[str, Any], names: Iterable[str]) -> dict[str, Any]:
    """``schema`` with ``names`` neither offered nor required, an empty ``required`` dropped."""
    dropped = frozenset(names)
    kept = {key: value for key, value in schema.items() if key != "required"}
    kept["properties"] = {
        name: fragment for name, fragment in schema["properties"].items() if name not in dropped
    }
    required = [name for name in schema.get("required", ()) if name not in dropped]
    if required:
        kept["required"] = required
    return kept
