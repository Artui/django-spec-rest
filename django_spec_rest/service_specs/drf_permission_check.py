from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from django.db.models import Model
from django.http import HttpRequest
from django_service_specs.authorization.permission_check import PermissionCheck
from rest_framework.permissions import BasePermission

from django_spec_rest.service_specs.build_offline_context import build_offline_context
from django_spec_rest.service_specs.permission_denied import permission_denied
from django_spec_rest.service_specs.translate_drf_refusals import translate_drf_refusals
from django_spec_rest.service_specs.utils import carried, offline_action
from django_spec_rest.types.offline_context import OfflineContext


class DRFPermissionCheck(PermissionCheck):
    """DRF permission classes asked the kernel's three questions, off HTTP."""

    def __init__(
        self,
        permission_classes: Sequence[type[BasePermission]],
        *,
        route_reads: Sequence[str] = (),
    ) -> None:
        self.permission_classes: tuple[type[BasePermission], ...] = tuple(permission_classes)
        self.route_reads: tuple[str, ...] = tuple(route_reads)

    def has_permission(
        self,
        principal: Any,
        spec: Any,
        *,
        arguments: Mapping[str, Any] | None = None,
        call_context: dict[str, Any] | None = None,
        request: Any = None,
        view: Any = None,
    ) -> bool:
        """Whether every class's ``has_permission`` admits ``principal``, raising on the first that does not."""
        request, view = self._pair(principal, arguments, call_context, request=request, view=view)
        for permission in self._permissions():
            with translate_drf_refusals():
                admitted = permission.has_permission(request, view)
            if not admitted:
                _deny(permission, request)
        return True

    def has_object_permission(
        self,
        principal: Any,
        spec: Any,
        target: Any,
        *,
        arguments: Mapping[str, Any] | None = None,
        call_context: dict[str, Any] | None = None,
        request: Any = None,
        view: Any = None,
    ) -> bool:
        """Whether every class's ``has_object_permission`` admits ``principal`` to a model ``target``."""
        if not isinstance(target, Model):
            return True
        request, view = self._pair(principal, arguments, call_context, request=request, view=view)
        for permission in self._permissions():
            with translate_drf_refusals():
                admitted = permission.has_object_permission(request, view, target)
            if not admitted:
                _deny(permission, request)
        return True

    def has_scope_permission(
        self,
        principal: Any,
        spec: Any,
        scope: Any,
        *,
        arguments: Mapping[str, Any] | None = None,
    ) -> bool:
        """Allows: DRF has no question for a set or a create, as the class docstring says."""
        return True

    def _permissions(self) -> list[BasePermission]:
        return [permission_class() for permission_class in self.permission_classes]

    def _pair(
        self,
        principal: Any,
        arguments: Mapping[str, Any] | None,
        call_context: Mapping[str, Any] | None,
        *,
        request: Any,
        view: Any,
    ) -> tuple[Any, Any]:
        """The request and view to ask the classes against: the call's, its offline pair's for each it lacks."""
        seeds = {"request": request, "view": view}
        request = carried("request", seeds, call_context)
        view = carried("view", seeds, call_context)
        plain = request if isinstance(request, HttpRequest) else None
        if plain is not None or request is None or view is None:
            offline = self._context(
                principal, arguments, offline_action(call_context), http_request=plain
            )
            request = offline.request if plain is not None or request is None else request
            view = offline.view if view is None else view
        return request, view

    def _context(
        self,
        principal: Any,
        arguments: Mapping[str, Any] | None,
        action: str | None,
        *,
        http_request: HttpRequest | None,
    ) -> OfflineContext:
        if arguments is None:
            return build_offline_context(principal, action=action, http_request=http_request)
        kwargs = {name: arguments[name] for name in self.route_reads if name in arguments}
        return build_offline_context(
            principal, action=action, http_request=http_request, kwargs=kwargs, query_params={}
        )


def _deny(permission: BasePermission, request: Any) -> None:
    raise permission_denied(
        request, getattr(permission, "message", None), getattr(permission, "code", None)
    )
