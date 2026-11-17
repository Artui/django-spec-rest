from __future__ import annotations

import importlib
import sys
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import Client
from django.urls import clear_url_caches, set_script_prefix
from django_service_specs import Output, Presenter, SpecLink

from django_spec_rest import SelectorListView, ServiceViewSet
from django_spec_rest.views import linked_affordances
from tests.testapp.models import Post
from tests.views import linked_views
from tests.views.linked_views import LISTING, ROUTES

pytestmark = pytest.mark.django_db

_URLS = "tests.views.linked_urls"


@pytest.fixture(autouse=True)
def _routes(settings: Any) -> None:
    settings.ROOT_URLCONF = _URLS


@pytest.fixture
def posts() -> tuple[Post, Post]:
    return Post.objects.create(title="draft"), Post.objects.create(title="out", published=True)


def _links(post: Post, base: str = "http://testserver") -> dict[str, dict[str, Any]]:
    return {
        "rename": {"available": True, "href": f"{base}/posts/{post.pk}/", "method": "PUT"},
        "publish": {
            "available": True,
            "href": f"{base}/posts/{post.pk}/publish/",
            "method": "POST",
        },
        "archive": {"available": True, "href": f"{base}/archive/{post.pk}/", "method": "DELETE"},
        "nowhere": {"available": True},
        "stray": {"available": True},
        "unnamed": {"available": True},
        "flag": {"available": True, "href": f"{base}/posts/{post.pk}/flag/", "method": "POST"},
    }


def _published(post: Post) -> dict[str, dict[str, Any]]:
    links = _links(post)
    links["publish"] = {
        **links["publish"],
        "available": False,
        "code": "already_published",
        "reason": "This post is already published.",
    }
    return links


@pytest.mark.parametrize("url", ["/linked/", "/posts/", "/posts/everything/"])
def test_each_list_route_carries_href_and_method(url: str, posts: tuple[Post, Post]) -> None:
    rows = Client().get(url).json()
    assert [row["affordances"] for row in rows] == [_links(posts[0]), _published(posts[1])]


@pytest.mark.parametrize("url", ["/linked/{pk}/", "/posts/{pk}/"])
def test_each_detail_route_carries_href_and_method(url: str, posts: tuple[Post, Post]) -> None:
    row = Client().get(url.format(pk=posts[1].pk)).json()
    assert row["affordances"] == _published(posts[1])


def test_no_link_routes_leaves_the_entries_as_they_were(posts: tuple[Post, Post]) -> None:
    rows = Client().get("/unlinked/").json()
    assert rows[0]["affordances"] == {name: {"available": True} for name in _links(posts[0])}


def test_a_bound_body_read_is_not_a_route_kwarg(posts: tuple[Post, Post]) -> None:
    """rename binds ``title`` as well as ``pk``; the route captures ``pk`` alone."""
    rows = Client().get("/linked/").json()
    assert rows[0]["affordances"]["rename"]["href"] == f"http://testserver/posts/{posts[0].pk}/"


def test_the_href_carries_the_script_prefix(posts: tuple[Post, Post]) -> None:
    """``resolve`` takes the path without the prefix the href carries; the client sets none."""
    set_script_prefix("/app/")
    try:
        rows = Client().get("/linked/").json()
    finally:
        set_script_prefix("/")
    assert rows[0]["affordances"] == _links(posts[0], base="http://testserver/app")


def test_a_row_missing_a_bound_field_keeps_its_answers_alone(posts: tuple[Post, Post]) -> None:
    """The kernel refuses the whole row, so create, which reads no ``id``, loses its href too."""
    rows = Client().get("/shaped/").json()
    assert rows[0]["affordances"]["rename"]["method"] == "PUT"
    assert rows[0]["affordances"]["create"]["method"] == "POST"
    assert rows[1]["affordances"] == {"rename": {"available": True}, "create": {"available": True}}


class _Unshaped(Presenter):
    def output(self) -> Output | None:
        return None

    def present(self, value: Any) -> Any:
        return {"id": value.pk}


def test_a_misnamed_field_with_no_output_to_check_it_raises(
    posts: tuple[Post, Post], rf: Any
) -> None:
    misnamed = LISTING.derive(
        presenter=_Unshaped(),
        affordances={"rename": SpecLink(linked_views.RENAME, arguments={"pk": "idd"})},
    )
    view = SelectorListView.as_view(spec=misnamed, link_routes=ROUTES)
    with pytest.raises(ImproperlyConfigured, match="idd"):
        view(rf.get("/"))


def test_the_map_is_declared_before_the_urlconf_loads(posts: tuple[Post, Post]) -> None:
    """The views module builds the registry and mounts its views while the URLconf imports it."""
    for name in (_URLS, linked_views.__name__):
        sys.modules.pop(name, None)
    clear_url_caches()
    try:
        importlib.import_module(_URLS)
        rows = Client().get("/linked/").json()
    finally:
        sys.modules[linked_views.__name__] = linked_views
        sys.modules.pop(_URLS, None)
        clear_url_caches()
    assert rows[0]["affordances"]["rename"]["href"] == f"http://testserver/posts/{posts[0].pk}/"


def test_link_routes_as_an_as_view_keyword(posts: tuple[Post, Post], rf: Any) -> None:
    view = SelectorListView.as_view(spec=LISTING, link_routes=ROUTES)
    response = view(rf.get("/"))
    response.render()
    assert response.data[0]["affordances"]["archive"]["method"] == "DELETE"


@pytest.mark.parametrize("base", [SelectorListView, ServiceViewSet], ids=lambda b: b.__name__)
def test_link_routes_must_be_a_registry(base: type) -> None:
    view: Any = type("_View", (base,), {"link_routes": {"archive": LISTING}})
    actions = ({"get": "list"},) if base is ServiceViewSet else ()
    with pytest.raises(ImproperlyConfigured, match=r"_View\.link_routes must be a SpecRegistry"):
        view.as_view(*actions)


def test_an_unbindable_link_still_raises(posts: tuple[Post, Post], rf: Any) -> None:
    """A binding refusal is the kernel's first-use backstop, never an omitted href."""
    unbound = LISTING.derive(affordances={"rename": SpecLink(linked_views.RENAME)})
    view = SelectorListView.as_view(spec=unbound, link_routes=ROUTES)
    with pytest.raises(ImproperlyConfigured, match="rename"):
        view(rf.get("/"))


def test_a_row_its_route_cannot_reverse_for_gets_no_href(db: Any) -> None:
    """The route captures the required ``title``; a slug refuses one row's and not the next's."""
    first = Post.objects.create(title="two words")
    second = Post.objects.create(title="draft")
    rows = Client().get("/titled/").json()
    create = {"available": True, "href": "http://testserver/create/", "method": "POST"}
    assert [row["affordances"] for row in rows] == [
        {
            "by_title": {"available": True},
            "create": create,
            "touch": {
                "available": True,
                "href": f"http://testserver/touches/{first.pk}/",
                "method": "PATCH",
            },
        },
        {
            "by_title": {
                "available": True,
                "href": "http://testserver/by-title/draft/",
                "method": "PUT",
            },
            "create": create,
            "touch": {
                "available": True,
                "href": f"http://testserver/touches/{second.pk}/",
                "method": "PATCH",
            },
        },
    ]


def test_each_route_s_method_is_found_once_a_response(
    posts: tuple[Post, Post], monkeypatch: pytest.MonkeyPatch
) -> None:
    found: list[str] = []
    method = linked_affordances._method

    def counted(href: str, route: str, routes: Any) -> str | None:
        found.append(route)
        return method(href, route, routes)

    monkeypatch.setattr(linked_affordances, "_method", counted)
    Client().get("/linked/")
    assert sorted(found) == [
        "archive",
        "linked-detail",
        "posts:posts-detail",
        "posts:posts-flag",
        "posts:posts-publish",
    ]


@pytest.mark.parametrize(
    ("url", "base"),
    [("/v2/rows/", "http://testserver/v2"), ("/n1/rows/", "http://testserver/n1")],
    ids=["url-path", "namespace"],
)
def test_the_href_follows_the_request_s_versioning(
    url: str, base: str, posts: tuple[Post, Post], settings: Any
) -> None:
    settings.ROOT_URLCONF = "tests.views.versioned_urls"
    rows = Client().get(url).json()
    assert rows[0]["affordances"]["rename"]["href"] == f"{base}/posts/{posts[0].pk}/"


def test_a_route_needing_a_read_the_link_does_not_require_gets_no_href(
    posts: tuple[Post, Post],
) -> None:
    """An untyped provider leaves ``required`` empty; the bound ``pk`` is not passed."""
    rows = Client().get("/loosely/").json()
    assert rows[0]["affordances"] == {"loose": {"available": True}}


def test_a_spec_with_no_affordances_presents_as_it_did(posts: tuple[Post, Post]) -> None:
    rows = Client().get("/plain/").json()
    assert rows == [{"id": post.pk, "title": post.title} for post in posts]
