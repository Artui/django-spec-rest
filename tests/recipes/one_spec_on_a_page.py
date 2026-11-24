from __future__ import annotations

from typing import Any

from django import forms
from django_service_specs import (
    DEFAULT_POOL_SEEDS,
    FormValidator,
    Parameter,
    Parameters,
    PermissionCheck,
    ServiceSpec,
)
from django_spec_html import SpecFormView
from rest_framework.permissions import BasePermission

from django_spec_rest import ServiceViewSet
from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from tests.testapp.models import Author, Post

# --8<-- [start:spec]
SEEDS = DEFAULT_POOL_SEEDS.extend(club=lambda *, request: request.club)


class IsClubMember(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        club_pk = view.kwargs["club_pk"]
        return Author.objects.filter(pk=club_pk, name=request.user.username).exists()


class PostForm(forms.Form):
    title = forms.CharField(max_length=200)


def add_post(*, data: dict[str, Any], club: Author) -> Post:
    return Post.objects.create(title=data["title"], author=club)


ADD_POST = ServiceSpec(
    service=add_post,
    validator=FormValidator(PostForm),
    permissions=(DRFPermissionCheck([IsClubMember]),),
)
# --8<-- [end:spec]


# --8<-- [start:mounts]
class ClubPostViewSet(ServiceViewSet):
    action_specs = {"create": ADD_POST}
    pool_seeds = SEEDS


add_post_page = SpecFormView.as_view(
    spec=ADD_POST,
    pool_seeds=SEEDS,
    route_kwargs={"club_pk": None},
    success_url="/posts/",
)
# --8<-- [end:mounts]


# --8<-- [start:bridge]
class IsClubOwner(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return view.get_club().name == request.user.username


class ClubRouteMixin:
    kwargs: dict[str, Any]

    def get_club(self) -> Author:
        return Author.objects.get(pk=self.kwargs["club_pk"])


OWNER_ADDS_POST = ServiceSpec(
    service=add_post,
    validator=FormValidator(PostForm),
    permissions=(DRFPermissionCheck([IsClubOwner]),),
)


class OwnerPostViewSet(ClubRouteMixin, ServiceViewSet):
    action_specs = {"create": OWNER_ADDS_POST}
    pool_seeds = SEEDS


class OwnerPostPage(ClubRouteMixin, SpecFormView):
    pass


owner_post_page = OwnerPostPage.as_view(
    spec=OWNER_ADDS_POST,
    pool_seeds=SEEDS,
    route_kwargs={"club_pk": None},
    success_url="/posts/",
)
# --8<-- [end:bridge]


# --8<-- [start:neutral]
class IsMemberOfClub(PermissionCheck):
    message = "Only the club's members may post."

    def has_permission(self, principal: Any, spec: Any, *, club: Author) -> bool:
        return club.name == principal.username


def add_club_post(*, data: dict[str, Any], club_pk: int) -> Post:
    return Post.objects.create(title=data["title"], author_id=club_pk)


ADD_CLUB_POST = ServiceSpec(
    service=add_club_post,
    validator=FormValidator(PostForm),
    reads=Parameters.of(Parameter("club_pk", "integer", required=True)),
    permissions=(IsMemberOfClub(),),
)


class ClubPostsViewSet(ServiceViewSet):
    action_specs = {"create": ADD_CLUB_POST}
    pool_seeds = SEEDS


add_club_post_page = SpecFormView.as_view(
    spec=ADD_CLUB_POST, pool_seeds=SEEDS, success_url="/posts/"
)
# --8<-- [end:neutral]


bare_owner_page = SpecFormView.as_view(
    spec=OWNER_ADDS_POST,
    pool_seeds=SEEDS,
    route_kwargs={"club_pk": None},
    success_url="/posts/",
)
