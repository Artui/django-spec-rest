"""Over HTTP, a key the server fills is the route's and never the body's, on a kernel spec.

drfs marked such a key ``NotClientInput`` on the callable's signature. A kernel
spec declares no parameter for it and fills it through a ``kwargs`` provider,
which may read the route through the seeded ``view``: the URLconf is the
author's, so a route capture fills it, and a body naming it is a key the spec
declares no argument for, answered by the edge's unknown-argument policy.

``view`` is a call seed, as ``request`` is: every callable declaring it is
handed the calling view, and a body key of that name never stands in for it.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    UnknownArguments,
    Unrestricted,
)
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorRetrieveView, ServiceUpdateView
from django_spec_rest.dispatch import kernel_edge
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Post
from tests.testapp.serializers import PostSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_SEEN: list[Any] = []


@pytest.fixture
def seen() -> Any:
    _SEEN.clear()
    yield _SEEN
    _SEEN.clear()


def _post_for_team(*, pk: int, team: str = "own-team") -> QuerySet[Post]:
    _SEEN.append(team)
    return Post.objects.filter(pk=pk)


def _team_from_the_route(view: Any) -> dict[str, Any]:
    """The server's value for ``team``: the route's capture, where the route has one."""
    return {"team": view.kwargs["team"]} if "team" in view.kwargs else {}


def _touch(*, instance: Post) -> Post:
    return instance


_LOOKUP = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=_post_for_team,
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
    kwargs=_team_from_the_route,
    permissions=_OPEN,
)


class _Open:
    """No permission classes, answered as the spine's views answer them:
    ``MutationFlowMixin.get_permissions`` reads a drfs-only spec field."""

    permission_classes: Any = []
    authentication_classes: Any = []

    def get_permissions(self) -> list[Any]:
        return []


class _View(_Open, ServiceUpdateView):
    spec = ServiceSpec(
        service=_touch,
        instance_selector_spec=_LOOKUP,
        permissions=_OPEN,
        presenter=SerializerPresenter(PostSerializer),
    )


def _put(body: dict[str, Any], **route: Any) -> Any:
    return _View.as_view()(factory.put("/", body, format="json"), **route)


def test_a_route_capture_fills_the_lookup_s_server_owned_key(seen: list[Any]) -> None:
    post = Post.objects.create(title="p")

    response = _put({}, pk=post.pk, team="route-team")

    assert response.status_code == 200, response.data
    assert seen == ["route-team"]


def test_without_a_route_capture_the_key_keeps_its_default(seen: list[Any]) -> None:
    post = Post.objects.create(title="p")

    response = _put({}, pk=post.pk)

    assert response.status_code == 200, response.data
    assert seen == ["own-team"]


@pytest.mark.parametrize(
    "policy",
    [
        pytest.param(
            UnknownArguments.REJECT,
            id="reject",
            marks=pytest.mark.xfail(
                strict=True,
                reason=(
                    "author code runs on a call the shape check refuses: the target lookup "
                    "comes before the shape check, so the lookup selector (and its kwargs "
                    "provider) is called for a body naming an undeclared key, which drfs "
                    "answered without ever calling it. Owner question, not a fix here."
                ),
            ),
        ),
        pytest.param(UnknownArguments.IGNORE, id="ignore"),
    ],
)
def test_the_body_s_value_for_the_key_never_fills_it(
    seen: list[Any], monkeypatch: pytest.MonkeyPatch, policy: UnknownArguments
) -> None:
    """The spec declares no ``team`` argument, so the edge's policy answers the body's:
    a ``400`` "Unknown argument." under ``REJECT``, dropped unseen under ``IGNORE``.
    Under neither does the lookup see it, and under ``REJECT`` the refused call
    runs no author code at all, which is what drfs answered: the ``seen == []``
    line is the one the held gap fails at."""
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", policy)
    post = Post.objects.create(title="p")

    response = _put({"team": "other-team"}, pk=post.pk, team="route-team")

    if policy is UnknownArguments.REJECT:
        assert response.status_code == 400
        assert [str(message) for message in response.data["team"]] == ["Unknown argument."]
        assert seen == []
    else:
        assert response.status_code == 200, response.data
        assert seen == ["route-team"]


def _post_seen_by_its_view(*, pk: int, view: Any) -> QuerySet[Post]:
    _SEEN.append(view)
    return Post.objects.filter(pk=pk)


class _ViewLookupView(_Open, ServiceUpdateView):
    spec = ServiceSpec(
        service=_touch,
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=_post_seen_by_its_view,
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
            permissions=_OPEN,
        ),
        permissions=_OPEN,
        presenter=SerializerPresenter(PostSerializer),
    )


def test_a_lookup_declaring_view_is_handed_the_calling_view(seen: list[Any]) -> None:
    post = Post.objects.create(title="p")

    response = _ViewLookupView.as_view()(factory.put("/", {}, format="json"), pk=post.pk)

    assert response.status_code == 200, response.data
    (view,) = seen
    assert isinstance(view, _ViewLookupView)
    assert view.kwargs == {"pk": post.pk}


def _the_view(*, view: Any) -> Post:
    _SEEN.append(view)
    return Post.objects.order_by("id").first()


class _SeedView(_Open, SelectorRetrieveView):
    serializer_class = PostSerializer
    spec = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=_the_view, permissions=_OPEN)


def test_a_selector_declaring_view_is_handed_the_calling_view(seen: list[Any]) -> None:
    Post.objects.create(title="p")

    response = _SeedView.as_view()(factory.get("/"))

    assert response.status_code == 200, response.data
    (view,) = seen
    assert isinstance(view, _SeedView)


@pytest.mark.parametrize(
    "policy", [UnknownArguments.REJECT, UnknownArguments.IGNORE], ids=["reject", "ignore"]
)
def test_a_query_string_naming_view_never_stands_in_for_it(
    seen: list[Any], monkeypatch: pytest.MonkeyPatch, policy: UnknownArguments
) -> None:
    """``view`` is a seed and no parameter, so a client's ``?view=`` is an unknown
    argument: refused under ``REJECT``, dropped under ``IGNORE``, and the selector
    is handed the calling view either way it runs."""
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", policy)
    Post.objects.create(title="p")

    response = _SeedView.as_view()(factory.get("/", {"view": "forged"}))

    if policy is UnknownArguments.REJECT:
        assert response.status_code == 400
        assert seen == []
    else:
        assert response.status_code == 200, response.data
        (view,) = seen
        assert isinstance(view, _SeedView)


def test_a_provider_handing_the_selector_the_view_is_refused(seen: list[Any]) -> None:
    """A provider's key never outranks a seed, so one answering ``view`` is refused."""
    Post.objects.create(title="p")
    spec = SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=_the_view,
        permissions=_OPEN,
        kwargs=lambda: {"view": "forged"},
    )
    view = type("_View", (_SeedView,), {"spec": spec}).as_view()

    with pytest.raises(ImproperlyConfigured, match=r"returned the key\(s\) \['view'\]"):
        view(factory.get("/"))
    assert seen == []


def _team_post(*, team: str = "own-team") -> Post:
    _SEEN.append(team)
    return Post.objects.order_by("id").first()


class _TeamRetrieveView(_Open, SelectorRetrieveView):
    serializer_class = PostSerializer
    spec = SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=_team_post,
        kwargs=_team_from_the_route,
        permissions=_OPEN,
    )


@pytest.mark.parametrize(
    ("route", "team"), [({"team": "route-team"}, "route-team"), ({}, "own-team")]
)
def test_a_route_capture_fills_a_selector_s_server_owned_key(
    seen: list[Any], route: dict[str, Any], team: str
) -> None:
    Post.objects.create(title="p")

    response = _TeamRetrieveView.as_view()(factory.get("/"), **route)

    assert response.status_code == 200, response.data
    assert seen == [team]


def _posts_for_team(*, team: str = "own-team") -> QuerySet[Post]:
    _SEEN.append(team)
    return Post.objects.order_by("id")


def _count(*, collection: QuerySet[Post]) -> dict[str, int]:
    return {"count": collection.count()}


class _CollectionView(_Open, ServiceUpdateView):
    spec = ServiceSpec(
        service=_count,
        collection_selector_spec=SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_posts_for_team,
            kwargs=_team_from_the_route,
            permissions=_OPEN,
        ),
        permissions=_OPEN,
    )


@pytest.mark.parametrize(
    ("route", "team"), [({"team": "route-team"}, "route-team"), ({}, "own-team")]
)
def test_a_route_capture_fills_a_collection_lookup_s_server_owned_key(
    seen: list[Any], route: dict[str, Any], team: str
) -> None:
    Post.objects.create(title="p")

    response = _CollectionView.as_view()(factory.put("/", {}, format="json"), **route)

    assert response.status_code == 200, response.data
    assert response.data == {"count": 1}
    assert seen == [team]


class _HookHandingTheViewOver(_SeedView):
    """Hands itself to the selector through a kwargs hook, as drfs allowed and dropped for the seed."""

    def get_selector_kwargs(self) -> dict[str, Any]:
        return {"view": self}


class _HookFillingTheKey(_TeamRetrieveView):
    """Fills the server-owned key through a kwargs hook, which outranked the route's capture on drfs."""

    def get_selector_kwargs(self) -> dict[str, Any]:
        return {"team": "hook-team"}


@pytest.mark.parametrize(
    "view", [_HookHandingTheViewOver, _HookFillingTheKey], ids=["hands-the-view", "fills-the-key"]
)
def test_a_selector_view_s_kwargs_hook_is_refused_when_the_view_is_built(
    seen: list[Any], view: type
) -> None:
    """Changed by design: drfs asked ``get_selector_kwargs`` and layered its answer over
    the route's capture; a kernel selector spec is handed its own ``kwargs`` provider's
    values and no view hook's, so an override would be silently unasked. It is refused
    at ``as_view()``, naming the hook and the provider to move it to, before any
    request runs the selector."""
    with pytest.raises(
        ImproperlyConfigured,
        match=r"overrides get_selector_kwargs, which never reaches a kernel spec.*"
        r"SelectorSpec\(kwargs=\.\.\.\)",
    ):
        view.as_view()

    assert seen == []
