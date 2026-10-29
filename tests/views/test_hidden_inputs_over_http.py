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
    reads=Parameters.of(Parameter("pk", "integer")),
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
    "policy", [UnknownArguments.REJECT, UnknownArguments.IGNORE], ids=["reject", "ignore"]
)
def test_the_body_s_value_for_the_key_never_fills_it(
    seen: list[Any], monkeypatch: pytest.MonkeyPatch, policy: UnknownArguments
) -> None:
    """The spec declares no ``team`` argument, so the edge's policy answers the body's:
    a ``400`` "Unknown argument." under ``REJECT``, dropped unseen under ``IGNORE``.
    Under neither does the lookup see it."""
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
            reads=Parameters.of(Parameter("pk", "integer")),
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
