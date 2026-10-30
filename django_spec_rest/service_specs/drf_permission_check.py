"""``DRFPermissionCheck`` - a spec's DRF ``permission_classes`` as the kernel's ``PermissionCheck``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from django.db.models import Model
from django.http import HttpRequest
from django_service_specs.authorization.permission_check import PermissionCheck
from rest_framework.permissions import BasePermission

from django_spec_rest.service_specs.build_offline_context import build_offline_context
from django_spec_rest.service_specs.drf_not_permitted import DRFNotPermitted
from django_spec_rest.service_specs.translate_drf_refusals import translate_drf_refusals
from django_spec_rest.service_specs.utils import carried, offline_action
from django_spec_rest.types.offline_context import OfflineContext


class DRFPermissionCheck(PermissionCheck):
    """DRF permission classes asked the kernel's three questions, off HTTP.

    The kernel asks a principal and a spec; a DRF permission class asks a
    request and a view. So each question asks every class in order, a fresh
    instance each time, as a DRF view's ``get_permissions`` does, against the
    request and view the call carries, else the offline pair
    [`build_offline_context`][django_spec_rest.service_specs.build_offline_context.build_offline_context]
    builds for the principal. The first refusal
    raises the dual-base
    [`DRFNotPermitted`][django_spec_rest.service_specs.drf_not_permitted.NotPermitted]
    with that class's own ``message`` and ``code``, so a client is told what
    a DRF view would have told it; returning ``False`` instead would leave the
    kernel to raise its own class with the generic wording. A class that
    raises its own refusal is asked inside
    [`translate_drf_refusals`][django_spec_rest.service_specs.translate_drf_refusals.translate_drf_refusals],
    so DRF's ``PermissionDenied`` leaves as that ``DRFNotPermitted`` with the
    class's message and code, and ``NotAuthenticated`` as
    [`DRFNotAuthenticated`][django_spec_rest.service_specs.drf_not_authenticated.DRFNotAuthenticated],
    which DRF still answers 401
    (``tests/service_specs/test_drf_refusals_on_the_kernel_route.py``).

    **The view's ``kwargs`` are filled from the call's arguments before the
    class-level check.** A permission scoping by a route capture reads
    ``view.kwargs["project_pk"]`` in ``has_permission``, and off HTTP there is
    no URLconf to put it there; asked against an empty mapping it would refuse
    every caller it means to admit. Each method opts in to the kernel's
    ``arguments`` channel by declaring the keyword, and the names that go onto
    ``view.kwargs`` are the ones a route would have captured: ``route_reads``,
    the arguments the spec's row lookup reads (``pk`` of an update's instance
    lookup, or of a retrieve). Where a transport asks with no arguments at all
    (``None``), nothing is filled, and the classes decide what an empty route
    means, as they would for a URL that captured nothing.

    **The request and view the call carries come first.** The class-level
    and object-level methods declare ``request`` and ``view``, so a call
    registering either as a seed hands it over, and ``call_context``, so a
    call that puts either in its context does: a transport running the
    kernel's ``dispatch`` carries the request a run arrived on, or a role
    view built for the operation, that way. Each is the seed, else the
    context's entry, and ``None`` in either place is no value. A carried
    view, or DRF ``Request``, is asked as it is, with nothing filled onto it. Where the call
    carries one and not the other, the missing half is the offline pair's,
    built as below, so no class is ever handed ``None`` for a request or a
    view; where it carries neither, the whole offline pair is asked. The
    offline view's ``action`` is the call's context's ``action``, where that
    is a non-empty string, so a class branching on ``view.action`` reads the
    operation's name; a carried view keeps its own. A carried Django
    request that DRF has not wrapped, the request a run arrived on as the
    kernel's call context holds it, is asked as a DRF ``Request`` around a
    copy of it, built as the offline pair is: its ``user`` the principal and
    its query string empty, replacing its own, which is the endpoint's the run
    arrived on. Asked with no arguments at all, nothing is routed and its own
    query string stays.

    **``has_object_permission`` asks only about a model instance**; any other
    target is allowed here, because a DRF class written for a row reads
    attributes off it.

    **``has_scope_permission`` allows.** The kernel asks it of a bulk call's set,
    a collection's rows and a create's ``None``, and DRF has no such question:
    on HTTP, a create and a collection action run the class-level check and no
    object check, and a DRF ``has_object_permission`` handed a ``QuerySet`` or
    ``None`` would raise ``AttributeError`` or decide on the wrong object. The
    class-level check has already run, with the view's ``kwargs`` filled, by
    the time the kernel asks this one.

    No state is kept between questions: the compiled spec holding this check is
    shared by every call and every thread, so each question builds its own
    request and view.
    """

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
                _deny(permission)
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
                _deny(permission)
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
        """The request and view to ask the classes against: the call's, its offline pair's for each it lacks.

        Seeds before the context, and ``None`` as no value, are ``carried``'s,
        so a ``None`` the context holds is filled here as an absent entry is
        (test_a_none_in_the_call_context_falls_through_to_an_offline_pair,
        which fails if the pair is skipped wherever the context names a key).
        One branch to coverage, so each half is named by the test that fails
        without it: test_a_view_alone_is_asked_beside_an_offline_request_for_the_principal
        (the request) and
        test_a_request_alone_is_asked_beside_an_offline_view_carrying_the_route
        (the view).
        """
        seeds = {"request": request, "view": view}
        request = carried("request", seeds, call_context)
        view = carried("view", seeds, call_context)
        plain = request if isinstance(request, HttpRequest) else None
        # Three conjuncts, one branch to coverage. The plain-request one is held
        # by test_a_carried_django_request_is_wrapped_beside_a_carried_view, where
        # a carried view would otherwise skip the block; the request choice inside
        # it by test_a_carried_django_request_is_wrapped_with_the_routed_query_string.
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


def _deny(permission: BasePermission) -> None:
    raise DRFNotPermitted(getattr(permission, "message", None), getattr(permission, "code", None))
