from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.test import RequestFactory
from django_service_specs import FormValidator, Parameter, Parameters, PermissionCheck, ServiceSpec
from django_spec_html import SpecFormView
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from tests.recipes.one_spec_on_a_page import (
    SEEDS,
    ClubPostsViewSet,
    ClubPostViewSet,
    OwnerPostViewSet,
    PostForm,
    add_club_post_page,
    add_post,
    add_post_page,
    bare_owner_page,
    owner_post_page,
)
from tests.testapp.models import Author, Post

pytestmark = pytest.mark.django_db

_PAIRS = {
    "a class reading view.kwargs": (ClubPostViewSet, add_post_page),
    "a class calling a bridged method": (OwnerPostViewSet, owner_post_page),
    "a kernel check reading the seed": (ClubPostsViewSet, add_club_post_page),
}


def _club() -> Author:
    return Author.objects.create(name="ana")


def _on_rest(viewset: Any, club: Author, user: User) -> Any:
    request = APIRequestFactory().post("/", {"title": "Hello"}, format="json")
    request.club = club
    force_authenticate(request, user=user)
    return viewset.as_view({"post": "create"})(request, club_pk=str(club.pk))


def _on_page(page: Callable[..., Any], club: Author, user: User, method: str = "post") -> Any:
    factory = RequestFactory()
    request = factory.post("/", {"title": "Hello"}) if method == "post" else factory.get("/")
    request.club, request.user = club, user
    return page(request, club_pk=club.pk)


def _posts() -> list[tuple[str, int]]:
    return list(Post.objects.values_list("title", "author"))


@pytest.mark.parametrize("pair", _PAIRS.values(), ids=list(_PAIRS))
def test_a_member_posts_on_the_viewset(pair: Any) -> None:
    club = _club()
    response = _on_rest(pair[0], club, User.objects.create(username="ana"))
    assert response.status_code == 201, response.data
    assert _posts() == [("Hello", club.pk)]


@pytest.mark.parametrize("pair", _PAIRS.values(), ids=list(_PAIRS))
def test_a_member_posts_on_the_page(pair: Any) -> None:
    club = _club()
    response = _on_page(pair[1], club, User.objects.create(username="ana"))
    assert response.status_code == 302
    assert _posts() == [("Hello", club.pk)]


@pytest.mark.parametrize("pair", _PAIRS.values(), ids=list(_PAIRS))
def test_a_member_is_shown_the_page(pair: Any) -> None:
    response = _on_page(pair[1], _club(), User.objects.create(username="ana"), "get")
    assert response.status_code == 200


@pytest.mark.parametrize("pair", _PAIRS.values(), ids=list(_PAIRS))
def test_an_outsider_is_refused_on_the_viewset(pair: Any) -> None:
    response = _on_rest(pair[0], _club(), User.objects.create(username="bo"))
    assert response.status_code == 403
    assert not Post.objects.exists()


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("pair", _PAIRS.values(), ids=list(_PAIRS))
def test_an_outsider_is_refused_on_the_page(pair: Any, method: str) -> None:
    with pytest.raises(PermissionDenied):
        _on_page(pair[1], _club(), User.objects.create(username="bo"), method)
    assert not Post.objects.exists()


def test_a_class_calling_a_viewset_method_fails_on_a_page_with_no_bridge() -> None:
    with pytest.raises(AttributeError, match="get_club"):
        _on_page(bare_owner_page, _club(), User.objects.create(username="ana"))


_SEEN: list[Any] = []


class _Recording(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        _SEEN.append((request, view))
        return True


@pytest.mark.parametrize("method", ["get", "post"])
def test_a_class_on_a_page_is_asked_a_drf_copy_of_the_request_and_the_page(method: str) -> None:
    """Pins the page's claims: a DRF ``Request`` over a POST copy, the page itself as the view."""
    _SEEN.clear()
    spec = ServiceSpec(
        service=add_post,
        validator=FormValidator(PostForm),
        permissions=(DRFPermissionCheck([_Recording]),),
    )
    page = SpecFormView.as_view(
        spec=spec, pool_seeds=SEEDS, route_kwargs={"club_pk": None}, success_url="/posts/"
    )
    club, user = _club(), User.objects.create(username="ana")
    factory = RequestFactory()
    raw = (
        factory.post("/?page=2", {"title": "Hello"})
        if method == "post"
        else factory.get("/?page=2")
    )
    raw.club, raw.user = club, user
    page(raw, club_pk=club.pk)
    ((request, view),) = _SEEN
    assert isinstance(request, Request) and request._request is not raw
    assert (request.method, request.user, request.club, dict(request.data)) == (
        "POST",
        user,
        club,
        {},
    )
    assert request.query_params["page"] == "2"
    assert isinstance(view, SpecFormView) and view.kwargs == {"club_pk": club.pk}
    assert not hasattr(view, "action")


def test_the_page_refuses_a_capture_the_spec_does_not_declare() -> None:
    """Why ``route_kwargs`` drops ``club_pk`` on the page, where the viewset drops it unasked."""
    page = SpecFormView.as_view(
        spec=ClubPostViewSet.action_specs["create"], pool_seeds=SEEDS, success_url="/p/"
    )
    with pytest.raises(
        ImproperlyConfigured, match="captures club_pk, which the spec does not declare"
    ):
        _on_page(page, _club(), User.objects.create(username="ana"))


class _RecordingCheck(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any, *, arguments: Any = None) -> bool:
        _SEEN.append(arguments)
        return True


def test_a_class_level_check_is_asked_no_arguments_on_the_page() -> None:
    """Why the page tells a check to read the seed: the page asks before it reads the form."""
    _SEEN.clear()
    spec = ServiceSpec(
        service=add_post,
        validator=FormValidator(PostForm),
        reads=Parameters.of(Parameter("club_pk", "integer", required=True)),
        permissions=(_RecordingCheck(),),
    )
    page = SpecFormView.as_view(spec=spec, pool_seeds=SEEDS, success_url="/posts/")
    viewset = type("_ViewSet", (ClubPostViewSet,), {"action_specs": {"create": spec}})
    club, user = _club(), User.objects.create(username="ana")
    _on_page(page, club, user)
    _on_rest(viewset, club, user)
    assert _SEEN[0] is None
    assert _SEEN[1]["club_pk"] == club.pk


def test_a_provider_calling_a_viewset_method_fails_on_the_page() -> None:
    def scoped(*, view: Any) -> dict[str, Any]:
        return {"club": view.filter_queryset(Author.objects.all()).get()}

    spec = ServiceSpec(
        service=add_post,
        validator=FormValidator(PostForm),
        permissions=(DRFPermissionCheck([]),),
        kwargs=scoped,
    )
    page = SpecFormView.as_view(spec=spec, route_kwargs={"club_pk": None}, success_url="/p/")
    with pytest.raises(AttributeError, match="filter_queryset"):
        _on_page(page, _club(), User.objects.create(username="ana"))
