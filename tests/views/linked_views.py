from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet
from django_service_specs import (
    Affordance,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    SpecLink,
    SpecRegistry,
    Unrestricted,
)
from rest_framework import serializers

from django_spec_rest import (
    DiscriminatedAction,
    SelectorListView,
    SelectorRetrieveView,
    ServiceViewSet,
    selector_action,
    service_action,
)
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Post

_OPEN = (Unrestricted(),)
_BY_PK = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, pk: Post.objects.filter(pk=pk).first(),
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
)


class PostOut(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()


def _rename(*, instance: Post, title: str) -> Post:
    instance.title = title
    instance.save(update_fields=["title"])
    return instance


def _write(**fields: Any) -> ServiceSpec:
    return ServiceSpec(
        service=lambda *, instance: instance,
        permissions=_OPEN,
        instance_selector_spec=_BY_PK,
        presenter=SerializerPresenter(PostOut),
        **fields,
    )


# Its own read ``title`` binds to the row's field, and travels in the body, not the route.
RENAME = ServiceSpec(
    service=_rename,
    permissions=_OPEN,
    instance_selector_spec=_BY_PK,
    reads=Parameters.of(Parameter("title", "string", required=True)),
    presenter=SerializerPresenter(PostOut),
)
PUBLISH = _write(
    affordances=[
        Affordance(
            code="already_published",
            reason="This post is already published.",
            when=Q(published=False),
        )
    ]
)
ARCHIVE = _write()
FLAG = _write()
UNFLAG = _write()
# Its target selector requires ``title``, which the route captures; a slug refuses a space.
BY_TITLE = ServiceSpec(
    service=lambda *, instance: instance,
    permissions=_OPEN,
    instance_selector_spec=SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, title: Post.objects.filter(title=title).first(),
        reads=Parameters.of(Parameter("title", "string", required=True)),
    ),
    presenter=SerializerPresenter(PostOut),
)
# No target selector: no required reads, so a route with no captures.
CREATE = ServiceSpec(
    service=lambda *, title: None,
    permissions=_OPEN,
    reads=Parameters.of(Parameter("title", "string", required=True)),
)
TOUCH = _write()
NOWHERE = _write()
STRAY = _write()
UNNAMED = _write()

# Declared at import, before the URLconf that imports this module has any patterns.
ROUTES = SpecRegistry()
ROUTES.register("posts:posts-detail", RENAME)
ROUTES.register("posts:posts-publish", PUBLISH)
ROUTES.register("archive", ARCHIVE)
ROUTES.register("nowhere", NOWHERE)
ROUTES.register("linked-detail", STRAY)
ROUTES.register("posts:posts-flag", FLAG)
ROUTES.register("by-title", BY_TITLE)
ROUTES.register("create", CREATE)
ROUTES.register("touch:touches-detail", TOUCH)

AFFORDANCES = {
    "rename": SpecLink(RENAME, arguments={"pk": "id"}),
    "publish": SpecLink(PUBLISH, arguments={"pk": "id"}),
    "archive": SpecLink(ARCHIVE, arguments={"pk": "id"}),
    "nowhere": SpecLink(NOWHERE, arguments={"pk": "id"}),
    "stray": SpecLink(STRAY, arguments={"pk": "id"}),
    "unnamed": SpecLink(UNNAMED, arguments={"pk": "id"}),
    "flag": SpecLink(FLAG, arguments={"pk": "id"}),
}


def _posts() -> QuerySet[Post]:
    return Post.objects.order_by("id")


LISTING = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=_posts,
    permissions=_OPEN,
    presenter=SerializerPresenter(PostOut),
    affordances=AFFORDANCES,
)
DETAIL = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, pk: Post.objects.filter(pk=pk),
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
    permissions=_OPEN,
    presenter=SerializerPresenter(PostOut),
    affordances=AFFORDANCES,
)


class _IdWhenDraft(PostOut):
    def to_representation(self, instance: Any) -> Any:
        shown = super().to_representation(instance)
        if instance.published:
            del shown["id"]
        return shown


# A row a presenter leaves ``id`` out of cannot fill rename's required ``pk``.
SHAPED = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=_posts,
    permissions=_OPEN,
    presenter=SerializerPresenter(_IdWhenDraft),
    affordances={"rename": SpecLink(RENAME, arguments={"pk": "id"}), "create": CREATE},
)


# A slug route reverses for one row's title and not for another's.
TITLED = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=_posts,
    permissions=_OPEN,
    presenter=SerializerPresenter(PostOut),
    affordances={
        "by_title": BY_TITLE,
        "create": CREATE,
        "touch": SpecLink(TOUCH, arguments={"pk": "id"}),
    },
)
PLAIN = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=_posts,
    permissions=_OPEN,
    presenter=SerializerPresenter(PostOut),
)


class LinkedList(SelectorListView):
    spec = LISTING
    link_routes = ROUTES


class LinkedDetail(SelectorRetrieveView):
    spec = DETAIL
    link_routes = ROUTES


class UnlinkedList(SelectorListView):
    spec = LISTING


class PostViewSet(ServiceViewSet):
    queryset = Post.objects.all()
    link_routes = ROUTES
    action_specs = {"list": LISTING, "retrieve": DETAIL, "update": RENAME}

    @service_action(PUBLISH, detail=True, methods=["post"])
    def publish(self, request: Any, pk: Any = None) -> None:
        """Stubbed: the decorator serves the spec."""

    @service_action(
        DiscriminatedAction(discriminator=lambda: "flag", specs={"flag": FLAG, "unflag": UNFLAG}),
        detail=True,
        methods=["post"],
    )
    def flag(self, request: Any, pk: Any = None) -> None:
        """Stubbed: the decorator serves the spec."""

    @selector_action(LISTING, detail=False)
    def everything(self, request: Any) -> None:
        """Stubbed: the decorator serves the spec."""


class TouchViewSet(ServiceViewSet):
    queryset = Post.objects.all()
    action_specs = {"partial_update": TOUCH}
