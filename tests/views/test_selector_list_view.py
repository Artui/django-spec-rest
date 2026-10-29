"""``SelectorListView`` over a kernel ``SelectorSpec``.

The spec's own ``presenter`` renders the rows, the page's rows alone when the
view paginates, and its affordance answers ride on each; a spec declaring
neither is rendered by the view's ``serializer_class``. DRF's filter backends
and paginator still wrap what the dispatch read.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.db.models import Q, QuerySet
from django_service_specs import (
    Affordance,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    UnknownArguments,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorListView
from django_spec_rest.dispatch import kernel_edge
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Author, Post
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _NameOnly(serializers.Serializer):
    name = serializers.CharField()


class _TwoPerPage(PageNumberPagination):
    page_size = 2


def _authors() -> QuerySet[Author]:
    return Author.objects.order_by("id")


def _listing(selector: Any = _authors, **fields: Any) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.LIST, selector=selector, permissions=_OPEN, **fields)


def _get(
    spec: SelectorSpec, path: str = "/", attrs: dict[str, Any] | None = None, **kw: Any
) -> Response:
    view = type("_View", (SelectorListView,), {"spec": spec, **(attrs or {})})
    response = view.as_view()(factory.get(path), **kw)
    response.render()
    return response


def _body(response: Response) -> Any:
    return json.loads(response.content)


@pytest.fixture
def three() -> list[Author]:
    return [Author.objects.create(name=name) for name in ("a", "b", "c")]


class TestThePresenter:
    def test_the_spec_s_presenter_renders_the_rows(self, three: list[Author]) -> None:
        """The presenter's serializer, not the view's ``serializer_class``:
        ``_NameOnly`` has no ``id``, which ``AuthorSerializer`` would add."""
        spec = _listing(presenter=SerializerPresenter(_NameOnly))
        body = _body(_get(spec, attrs={"serializer_class": AuthorSerializer}))
        assert body == [{"name": "a"}, {"name": "b"}, {"name": "c"}]

    def test_a_spec_with_no_presenter_is_rendered_by_serializer_class(
        self, three: list[Author]
    ) -> None:
        body = _body(_get(_listing(), attrs={"serializer_class": AuthorSerializer}))
        assert body == [{"id": author.pk, "name": author.name} for author in three]

    def test_the_presenter_is_handed_the_page_s_rows_alone(self, three: list[Author]) -> None:
        handed: list[Any] = []

        class _Recording(SerializerPresenter):
            def presented_rows(self, items: Any, context: Any) -> Any:
                handed.extend(items)
                return super().presented_rows(items, context)

        spec = _listing(presenter=_Recording(_NameOnly))
        body = _body(_get(spec, attrs={"pagination_class": _TwoPerPage}))
        assert body["count"] == 3
        assert body["results"] == [{"name": "a"}, {"name": "b"}]
        assert handed == three[:2]

    def test_filter_backends_wrap_the_set_the_dispatch_read(self, three: list[Author]) -> None:
        class _OnlyB:
            def filter_queryset(self, request: Any, queryset: Any, view: Any) -> Any:
                return queryset.filter(name="b")

        spec = _listing(presenter=SerializerPresenter(_NameOnly))
        assert _body(_get(spec, attrs={"filter_backends": (_OnlyB,)})) == [{"name": "b"}]

    def test_a_selector_may_return_a_plain_list(self, three: list[Author]) -> None:
        spec = _listing(lambda: list(_authors()), presenter=SerializerPresenter(_NameOnly))
        body = _body(_get(spec, attrs={"pagination_class": _TwoPerPage}))
        assert body["count"] == 3
        assert body["results"] == [{"name": "a"}, {"name": "b"}]

    def test_shaping_on_a_selector_returning_a_list_fails_loud(self) -> None:
        spec = _listing(lambda: [], presenter=SerializerPresenter(_NameOnly), select_related=("x",))
        with pytest.raises(ImproperlyConfigured, match="QuerySet"):
            _get(spec)

    def test_a_list_selector_s_object_does_not_exist_propagates(self) -> None:
        """Only a RETRIEVE's miss is a 404; a list's is the selector's bug."""

        def boom() -> Any:
            raise ObjectDoesNotExist

        with pytest.raises(ObjectDoesNotExist):
            _get(_listing(boom, presenter=SerializerPresenter(_NameOnly)))

    def test_get_queryset_is_the_set_the_dispatch_read(self, three: list[Author]) -> None:
        """DRF's own machinery calling ``get_queryset()`` (a schema generator,
        a subclass) is handed the spec's set, unpresented."""
        view = type("_View", (SelectorListView,), {"spec": _listing()})()
        view.setup(factory.get("/"))
        view.request = view.initialize_request(view.request)
        view.format_kwarg = None
        assert list(view.get_queryset()) == three


class TestTheArguments:
    def test_a_declared_route_capture_reaches_the_selector(self, three: list[Author]) -> None:
        received: dict[str, Any] = {}

        def by_author(*, author_id: int) -> QuerySet[Author]:
            received["author_id"] = author_id
            return Author.objects.filter(pk=author_id)

        spec = _listing(
            by_author,
            reads=Parameters.of(Parameter("author_id", "integer")),
            presenter=SerializerPresenter(_NameOnly),
        )
        assert _body(_get(spec, author_id=str(three[1].pk))) == [{"name": "b"}]
        # Coerced to the Parameter's type, as the route handed a string.
        assert received == {"author_id": three[1].pk}

    def test_the_spec_s_kwargs_provider_reaches_the_selector(self) -> None:
        received: dict[str, Any] = {}

        def selector(*, tenant_id: int) -> QuerySet[Author]:
            received["tenant_id"] = tenant_id
            return Author.objects.none()

        def provider() -> dict[str, Any]:
            return {"tenant_id": 12}

        spec = _listing(selector, kwargs=provider, presenter=SerializerPresenter(_NameOnly))
        assert _get(spec).status_code == 200
        assert received == {"tenant_id": 12}

    @pytest.mark.xfail(
        strict=True,
        reason="dispatch_kernel_spec takes no extra_kwargs, so the view's hook chain "
        "(get_selector_kwargs) never reaches a kernel spec; an ask on dispatch/kernel_edge.py",
    )
    def test_get_selector_kwargs_reaches_the_selector(self) -> None:
        received: dict[str, Any] = {}

        def selector(*, tenant: str) -> QuerySet[Author]:
            received["tenant"] = tenant
            return Author.objects.none()

        spec = _listing(selector, presenter=SerializerPresenter(_NameOnly))
        hooks = {"get_selector_kwargs": lambda self: {"tenant": "acme"}}
        assert _get(spec, attrs=hooks).status_code == 200
        assert received == {"tenant": "acme"}


_REFUSED_KEYS = pytest.mark.xfail(
    strict=True,
    reason="dispatch_kernel_spec reads request.query_params whole; selectors.utils.kernel_query "
    "strips DRF's own keys and needs a query= hand-off on dispatch/kernel_edge.py",
)


class TestDRFsOwnQueryKeys:
    """DRF's own keys are no argument of the spec's, under either policy.

    Under ``IGNORE`` an undeclared key is dropped unseen already; under
    ``REJECT`` it reaches the closed argument set and is refused, which the
    strip is for. Each policy's answer is asserted, so the owner's choice
    moves one line and no test.
    """

    @pytest.mark.parametrize(
        "policy",
        [pytest.param(UnknownArguments.REJECT, marks=_REFUSED_KEYS), UnknownArguments.IGNORE],
    )
    @pytest.mark.parametrize(
        ("query", "attrs"),
        [
            ("?page=2", {"pagination_class": _TwoPerPage}),
            ("?ordering=-name", {"filter_backends": (OrderingFilter,)}),
            ("?search=a", {"filter_backends": (SearchFilter,), "search_fields": ("name",)}),
            ("?format=json", {}),
        ],
    )
    def test_a_drf_key_is_read_by_drf_and_never_by_the_kernel(
        self,
        monkeypatch: pytest.MonkeyPatch,
        three: list[Author],
        policy: UnknownArguments,
        query: str,
        attrs: dict[str, Any],
    ) -> None:
        monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", policy)
        spec = _listing(presenter=SerializerPresenter(_NameOnly))
        response = _get(spec, query, attrs={"ordering_fields": ("name",), **attrs})
        assert response.status_code == 200, response.content
        body = _body(response)
        rows = body["results"] if "page" in query else body
        expected = {
            "?page=2": [{"name": "c"}],
            "?ordering=-name": [{"name": "c"}, {"name": "b"}, {"name": "a"}],
            "?search=a": [{"name": "a"}],
            "?format=json": [{"name": "a"}, {"name": "b"}, {"name": "c"}],
        }
        assert rows == expected[query]

    @pytest.mark.parametrize("policy", [UnknownArguments.REJECT, UnknownArguments.IGNORE])
    def test_an_undeclared_key_of_no_drf_reader_answers_by_the_policy(
        self, monkeypatch: pytest.MonkeyPatch, policy: UnknownArguments
    ) -> None:
        monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", policy)
        response = _get(_listing(presenter=SerializerPresenter(_NameOnly)), "?nope=1")
        if policy is UnknownArguments.REJECT:
            assert response.status_code == 400
            assert _body(response) == {"nope": ["Unknown argument."]}
        else:
            assert response.status_code == 200


UNPUBLISHED = Affordance(
    code="already_published", reason="This post is already published.", when=Q(published=False)
)
PUBLISH = ServiceSpec(service=lambda: None, permissions=_OPEN, affordances=[UNPUBLISHED])
_AVAILABLE = {"publish": {"available": True}}
_REFUSED = {
    "publish": {
        "available": False,
        "code": "already_published",
        "reason": "This post is already published.",
    }
}


class _PostOut(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()


@pytest.fixture
def posts() -> tuple[Post, Post]:
    return Post.objects.create(title="draft"), Post.objects.create(title="out", published=True)


def _posts() -> QuerySet[Post]:
    return Post.objects.order_by("id")


class TestAffordances:
    def test_each_row_carries_its_answers(self, posts: tuple[Post, Post]) -> None:
        spec = _listing(
            _posts, presenter=SerializerPresenter(_PostOut), affordances={"publish": PUBLISH}
        )
        body = _body(_get(spec))
        assert [row["affordances"] for row in body] == [_AVAILABLE, _REFUSED]
        assert [row["title"] for row in body] == ["draft", "out"]

    def test_a_page_s_rows_carry_theirs_inside_the_paginator_s_envelope(
        self, posts: tuple[Post, Post]
    ) -> None:
        class _OnePerPage(PageNumberPagination):
            page_size = 1

        spec = _listing(
            _posts, presenter=SerializerPresenter(_PostOut), affordances={"publish": PUBLISH}
        )
        body = _body(_get(spec, attrs={"pagination_class": _OnePerPage}))
        assert body["count"] == 2
        assert [row["affordances"] for row in body["results"]] == [_AVAILABLE]

    def test_affordances_with_no_presenter_are_refused_rather_than_dropped(
        self, posts: tuple[Post, Post]
    ) -> None:
        """``serializer_class`` cannot carry the answers, so the kernel's
        ``present`` refuses the spec rather than serving rows without them."""
        spec = _listing(_posts, affordances={"publish": PUBLISH})
        with pytest.raises(ImproperlyConfigured, match="Declare a presenter"):
            _get(spec, attrs={"serializer_class": _PostOut})
