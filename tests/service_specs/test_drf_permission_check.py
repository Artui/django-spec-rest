"""``DRFPermissionCheck``: DRF permission classes as a kernel spec's own ``permissions``.

Every case hands a kernel spec to the kernel's ``authorize``, ``authorize_target``
or ``dispatch``, so the kernel's own reading of each opt-in - ``arguments``,
``call_context``, ``request`` and ``view`` - is what is tested, not a direct call
that would pass whether or not the kernel ever handed them over. The route a
kernel spec's check fills onto an offline view is ``route_reads`` alone: the
``UrlKwarg`` and ``QueryParam`` declarations the check also takes are drfs' and
stay with its tests.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser, User
from django.http import HttpRequest
from django.test import RequestFactory
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
)
from django_service_specs.authorization.not_permitted import NotPermitted as KernelNotPermitted
from django_service_specs.dispatch.authorize import authorize
from django_service_specs.dispatch.authorize_target import authorize_target
from django_service_specs.dispatch.dispatch import dispatch
from rest_framework.exceptions import NotAuthenticated, PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from django_spec_rest.service_specs.build_offline_context import build_offline_context
from django_spec_rest.service_specs.drf_not_authenticated import DRFNotAuthenticated
from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from django_spec_rest.service_specs.not_permitted import NotPermitted
from tests.testapp.models import Post

_SEEN: list[dict[str, Any]] = []
_PK = Parameters.of(Parameter("pk", "integer"))


class _OnlySeven(BasePermission):
    """Admits the call whose route captured ``pk`` 7, as a nested-route permission does."""

    message = "Only row seven."
    code = "not_seven"

    def has_permission(self, request: Any, view: Any) -> bool:
        return view.kwargs.get("pk") == 7


class _Records(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        _SEEN.append(
            {
                "kwargs": dict(view.kwargs),
                "query": dict(request.query_params.lists()),
                "user": request.user,
                "action": view.action,
            }
        )
        return True


class _NoObjects(BasePermission):
    def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
        return False


class _RaisesOnAnyObject(BasePermission):
    def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
        raise AssertionError(f"asked about {obj!r}, which DRF never asks about")


def _check(*classes: type[BasePermission], route_reads: tuple[str, ...] = ()) -> Any:
    return (DRFPermissionCheck(classes, route_reads=route_reads),)


def _lookup(*, pk: int) -> Any:
    return Post.objects.filter(pk=pk).first()


def _update(*, instance: Any) -> Any:
    return instance


def _create() -> dict[str, bool]:
    return {"created": True}


def _retrieve(*classes: type[BasePermission], route: bool = True) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=_lookup,
        reads=_PK,
        permissions=_check(*classes, route_reads=("pk",) if route else ()),
    )


@pytest.fixture(autouse=True)
def _clear() -> None:
    _SEEN.clear()


def _recorded() -> dict[str, Any]:
    (seen,) = _SEEN
    return seen


class TestTheRouteIsFilledBeforeTheClassLevelCheck:
    def test_a_class_reading_view_kwargs_sees_the_route_read(self) -> None:
        spec = ServiceSpec(
            service=_update,
            instance_selector_spec=_retrieve(),
            permissions=_check(_OnlySeven, route_reads=("pk",)),
        )

        authorize(spec, AnonymousUser(), arguments={"pk": 7})
        with pytest.raises(NotPermitted):
            authorize(spec, AnonymousUser(), arguments={"pk": 8})

    def test_an_argument_the_check_names_no_route_read_for_is_not_its_route(self) -> None:
        spec = _retrieve(_Records, route=False)

        authorize(spec, AnonymousUser(), arguments={"pk": 3})

        assert _recorded()["kwargs"] == {}
        assert _recorded()["query"] == {}

    def test_a_route_read_the_call_left_out_is_absent(self) -> None:
        authorize(_retrieve(_Records), AnonymousUser(), arguments={})

        assert _recorded()["kwargs"] == {}

    def test_no_arguments_fills_nothing(self) -> None:
        spec = ServiceSpec(service=_create, permissions=_check(_Records, route_reads=("pk",)))

        authorize(spec, AnonymousUser())

        assert _recorded()["kwargs"] == {}

    def test_the_principal_is_the_request_s_user(self) -> None:
        principal = AnonymousUser()

        authorize(ServiceSpec(service=_create, permissions=_check(_Records)), principal)

        assert _recorded()["user"] is principal


class TestARefusal:
    def test_carries_the_class_s_message_and_code_as_both_bases(self) -> None:
        with pytest.raises(NotPermitted) as refused:
            authorize(_retrieve(_OnlySeven), AnonymousUser(), arguments={"pk": 1})

        assert isinstance(refused.value, KernelNotPermitted)
        assert isinstance(refused.value, PermissionDenied)
        assert refused.value.message == "Only row seven."
        assert refused.value.get_codes() == "not_seven"

    def test_the_first_refusing_class_answers_and_the_rest_are_not_asked(self) -> None:
        with pytest.raises(NotPermitted):
            authorize(_retrieve(_OnlySeven, _Records), AnonymousUser(), arguments={"pk": 1})

        assert _SEEN == []

    @pytest.mark.django_db
    def test_a_drf_permission_denied_raised_by_a_class_leaves_dispatch_as_not_permitted(
        self,
    ) -> None:
        # A class that raises its refusal rather than returning ``False`` is a
        # fault off DRF unless the check translates it.
        class _Raises(BasePermission):
            def has_permission(self, request: Any, view: Any) -> bool:
                raise PermissionDenied("Not on Sundays.", code="sunday")

        spec = ServiceSpec(service=_create, permissions=_check(_Raises))

        with pytest.raises(KernelNotPermitted) as refused:
            dispatch(spec, principal=AnonymousUser(), arguments={})

        assert isinstance(refused.value, NotPermitted)
        assert refused.value.message == "Not on Sundays."
        assert refused.value.get_codes() == "sunday"

    @pytest.mark.django_db
    def test_a_drf_not_authenticated_leaves_dispatch_as_drf_s_401_twin(self) -> None:
        class _Anonymous(BasePermission):
            def has_permission(self, request: Any, view: Any) -> bool:
                raise NotAuthenticated()

        spec = ServiceSpec(service=_create, permissions=_check(_Anonymous))

        with pytest.raises(DRFNotAuthenticated):
            dispatch(spec, principal=AnonymousUser(), arguments={})


@pytest.mark.django_db
class TestTheObjectCheck:
    def test_a_model_row_is_asked_about(self) -> None:
        post = Post.objects.create(title="t")

        with pytest.raises(NotPermitted):
            dispatch(_retrieve(_NoObjects), principal=AnonymousUser(), arguments={"pk": post.pk})

    def test_a_model_row_every_class_admits_is_returned(self) -> None:
        post = Post.objects.create(title="t")

        result = dispatch(_retrieve(_Records), principal=AnonymousUser(), arguments={"pk": post.pk})

        assert result.value == post

    def test_a_target_that_is_no_model_is_not_asked_about(self) -> None:
        spec = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, pk: {"pk": pk},
            reads=_PK,
            permissions=_check(_NoObjects),
        )

        result = dispatch(spec, principal=AnonymousUser(), arguments={"pk": 2})

        assert result.value == {"pk": 2}


@pytest.mark.django_db
class TestTheScopeCheck:
    def test_a_create_is_never_asked_about_an_object(self) -> None:
        spec = ServiceSpec(service=_create, permissions=_check(_RaisesOnAnyObject))

        result = dispatch(spec, principal=AnonymousUser(), arguments={})

        assert result.value == {"created": True}

    def test_a_collection_is_never_asked_about_an_object(self) -> None:
        Post.objects.create(title="t")
        spec = ServiceSpec(
            service=lambda *, collection: collection.count(),
            collection_selector_spec=SelectorSpec(
                kind=SelectorKind.LIST,
                selector=lambda: Post.objects.all(),
                permissions=_check(),
            ),
            permissions=_check(_RaisesOnAnyObject),
        )

        result = dispatch(spec, principal=AnonymousUser(), arguments={})

        assert result.value == 1


_ASKED: list[tuple[Any, Any]] = []


class _Pairs(BasePermission):
    """Records the request and view each question was asked against."""

    def has_permission(self, request: Any, view: Any) -> bool:
        _ASKED.append((request, view))
        return True

    def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
        _ASKED.append((request, view))
        return True


def _asked() -> tuple[Any, Any]:
    (pair,) = _ASKED
    _ASKED.clear()
    return pair


def _real_pair(name: str) -> tuple[Any, Any]:
    """A request and a view standing for ones a transport carries, told apart by ``action``."""
    request = build_offline_context(AnonymousUser()).request
    return request, SimpleNamespace(request=request, kwargs={}, action=name)


class TestTheCallsRequestAndView:
    """The request and view the call's context carries, before an offline pair."""

    @pytest.fixture(autouse=True)
    def _clear_asked(self) -> None:
        _ASKED.clear()

    def _spec(self, route_reads: tuple[str, ...] = ()) -> ServiceSpec:
        return ServiceSpec(service=_create, permissions=_check(_Pairs, route_reads=route_reads))

    def test_the_call_context_s_pair_is_asked(self) -> None:
        request, view = _real_pair("in-context")

        authorize(self._spec(), AnonymousUser(), call_context={"request": request, "view": view})

        assert _asked() == (request, view)

    def test_a_none_in_the_call_context_falls_through_to_an_offline_pair(self) -> None:
        principal = AnonymousUser()

        authorize(
            self._spec(("pk",)),
            principal,
            arguments={"pk": 4},
            call_context={"request": None, "view": None, "format": None, "action": None},
        )

        request, view = _asked()
        assert request.user is principal
        assert view.kwargs == {"pk": 4}

    def test_a_view_alone_is_asked_beside_an_offline_request_for_the_principal(self) -> None:
        principal = AnonymousUser()
        _, view = _real_pair("role")

        authorize(self._spec(), principal, call_context={"request": None, "view": view})

        request, asked_view = _asked()
        assert asked_view is view
        assert request.user is principal

    def test_a_request_alone_is_asked_beside_an_offline_view_carrying_the_route(self) -> None:
        request, _ = _real_pair("arrived-on")

        authorize(
            self._spec(("pk",)),
            AnonymousUser(),
            arguments={"pk": 4},
            call_context={"request": request},
        )

        asked_request, view = _asked()
        assert asked_request is request
        assert view.kwargs == {"pk": 4}

    @pytest.mark.django_db
    def test_the_object_check_is_asked_against_the_call_s_pair(self) -> None:
        post = Post.objects.create(title="t")
        request, view = _real_pair("in-context")
        spec = _retrieve(_Pairs)
        # Minted for this very spec, which the check is asked about again: a
        # ``Grant`` covers only the spec it was minted for, by identity.
        grant = authorize(spec, AnonymousUser(), arguments={"pk": post.pk})
        _ASKED.clear()

        authorize_target(
            spec,
            AnonymousUser(),
            post,
            grant=grant,
            arguments={"pk": post.pk},
            call_context={"request": request, "view": view},
        )

        assert _asked() == (request, view)

    def test_the_offline_view_s_action_is_the_operation_s_name(self) -> None:
        # A transport running the kernel's dispatch builds no DRF view and names
        # the operation in the context, so a class branching on ``view.action``
        # reads it.
        authorize(self._spec(), AnonymousUser(), call_context={"view": None, "action": "publish"})

        _, view = _asked()
        assert view.action == "publish"

    @pytest.mark.django_db
    def test_a_class_branching_on_view_action_off_http_reads_the_operation_s_name(
        self,
    ) -> None:
        class _OnlyPublish(BasePermission):
            def has_permission(self, request: Any, view: Any) -> bool:
                return view.action == "publish"

        spec = ServiceSpec(service=_create, permissions=_check(_OnlyPublish))

        dispatch(spec, principal=AnonymousUser(), arguments={}, call_context={"action": "publish"})
        with pytest.raises(NotPermitted):
            dispatch(
                spec, principal=AnonymousUser(), arguments={}, call_context={"action": "archive"}
            )

    def test_an_offline_view_beside_a_carried_request_takes_the_action_too(self) -> None:
        request, _ = _real_pair("arrived-on")

        authorize(
            self._spec(), AnonymousUser(), call_context={"request": request, "action": "publish"}
        )

        asked_request, view = _asked()
        assert asked_request is request
        assert view.action == "publish"

    @pytest.mark.parametrize("action", ["", 5], ids=["empty", "not-a-string"])
    def test_an_action_that_is_no_name_leaves_the_offline_view_s_as_it_was(
        self, action: Any
    ) -> None:
        authorize(self._spec(), AnonymousUser(), call_context={"action": action})

        _, view = _asked()
        assert view.action is None

    def test_a_carried_view_s_action_is_never_overwritten(self) -> None:
        request, view = _real_pair("role")

        authorize(
            self._spec(),
            AnonymousUser(),
            call_context={"request": request, "view": view, "action": "publish"},
        )

        assert _asked()[1].action == "role"

    def test_a_carried_django_request_is_wrapped_with_an_empty_query_string(self) -> None:
        # The arrived-on request's query string is its endpoint's, not this
        # operation's, and a kernel spec's check routes no query parameter.
        principal = AnonymousUser()
        arrived = RequestFactory().get("/chat/", {"thread": "7"})

        authorize(
            self._spec(),
            principal,
            arguments={},
            call_context={"request": arrived, "view": None, "action": "publish"},
        )

        request, view = _asked()
        assert isinstance(request, Request)
        assert dict(request.query_params.lists()) == {}
        assert request.user is principal
        assert view.request is request
        assert view.action == "publish"
        assert dict(arrived.GET.lists()) == {"thread": ["7"]}

    def test_a_carried_django_request_is_wrapped_beside_a_carried_view(self) -> None:
        principal = AnonymousUser()
        arrived = RequestFactory().get("/chat/")
        arrived.user = "arrived-user"
        carried_view = APIView()
        carried_view.action = "publish"
        carried_view.kwargs = {}

        authorize(
            self._spec(),
            principal,
            arguments={},
            call_context={"request": arrived, "view": carried_view},
        )

        request, view = _asked()
        assert isinstance(request, Request)
        assert not isinstance(request, HttpRequest)
        assert request.user is principal
        assert view is carried_view


@pytest.mark.django_db
class TestRequestAuth:
    """A wrapped or offline request's ``auth`` is ``None``, set without running DRF's authenticators.

    DRF's ``request.auth`` authenticates on first read, and a request built off
    DRF has no authenticator, so the read would set ``request.user`` to
    ``AnonymousUser`` and a class reading ``auth`` before ``user`` - a token
    scope check - would refuse a signed-in caller.
    """

    @pytest.fixture
    def principal(self) -> User:
        return User.objects.create(username="signed-in")

    def _reads_auth_first(self) -> tuple[type[BasePermission], list[Any]]:
        seen: list[Any] = []

        class _ReadsAuthFirst(BasePermission):
            def has_permission(self, request: Any, view: Any) -> bool:
                seen.append(request.auth)
                seen.append(request.user)
                return request.user.is_authenticated

        return _ReadsAuthFirst, seen

    def test_a_class_reading_auth_first_still_sees_the_principal(self, principal: User) -> None:
        permission, seen = self._reads_auth_first()
        spec = ServiceSpec(service=_create, permissions=_check(permission))

        dispatch(spec, principal=principal, arguments={})

        assert seen == [None, principal]

    def test_on_a_wrapped_django_request_too(self, principal: User) -> None:
        permission, seen = self._reads_auth_first()
        arrived = RequestFactory().get("/chat/")
        spec = ServiceSpec(service=_create, permissions=_check(permission))

        dispatch(spec, principal=principal, arguments={}, call_context={"request": arrived})

        assert seen == [None, principal]
        # The ``auth`` written lands on the wrapped copy alone.
        assert not hasattr(arrived, "auth")
