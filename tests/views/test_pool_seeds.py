"""A view's ``pool_seeds``: the seeds its spec's callables are resolved with, at mount and per call.

A spec whose affordance condition, precondition, selector or permission check
reads a registered seed is served by a view registering it, as a class
attribute or as ``as_view(pool_seeds=...)``, and refused at ``as_view()`` by a
view that does not. Each test drives a view through ``as_view()`` and reads
the answer off the response, so each fails against a tree with no seat.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet
from django_service_specs import (
    DEFAULT_POOL_SEEDS,
    Affordance,
    Parameter,
    Parameters,
    PermissionCheck,
    PoolSeeds,
    SelectorKind,
    SelectorSpec,
    ServiceError,
    ServiceSpec,
    Unrestricted,
)
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import (
    SelectorListView,
    SelectorRetrieveView,
    ServiceCreateView,
    ServiceDeleteView,
    ServiceUpdateView,
    ServiceViewSet,
    selector_action,
    service_action,
)
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Post
from tests.testapp.serializers import PostSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)

# The ambient fact the specs below read, behind the seed that resolves it.
_BOARD = {"frozen": False}
SEEDS = DEFAULT_POOL_SEEDS.extend(frozen=lambda: _BOARD["frozen"])

NOT_FROZEN = Affordance(
    code="board_frozen", reason="The board is frozen.", when=lambda *, frozen: not frozen
)


@pytest.fixture(autouse=True)
def _thawed() -> Any:
    _BOARD["frozen"] = False
    yield
    _BOARD["frozen"] = False


def _publish(*, instance: Post) -> Post:
    instance.published = True
    instance.save(update_fields=["published"])
    return instance


def _refuse_when_frozen(*, frozen: bool) -> None:
    if frozen:
        raise ServiceError("The board is frozen.")


_BY_PK = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, pk: Post.objects.filter(pk=pk).first(),
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
)


def _publish_spec(**fields: Any) -> ServiceSpec:
    return ServiceSpec(
        service=_publish,
        permissions=fields.pop("permissions", _OPEN),
        instance_selector_spec=_BY_PK,
        presenter=SerializerPresenter(PostSerializer),
        **fields,
    )


GUARDED = _publish_spec(affordances=[NOT_FROZEN])
PRECONDITIONED = _publish_spec(preconditions=[_refuse_when_frozen])


def _patch(view: Any, pk: int) -> tuple[int, Any]:
    response = view(factory.patch("/", {}, format="json"), pk=str(pk))
    response.render()
    return response.status_code, json.loads(response.content)


def _update_view(spec: ServiceSpec, **attrs: Any) -> type[ServiceUpdateView]:
    return type("_View", (ServiceUpdateView,), {"spec": spec, **attrs})


def _mounts() -> dict[str, Any]:
    """The two ways a view registers ``SEEDS``, each mounted over ``GUARDED``."""
    return {
        "class attribute": _update_view(GUARDED, pool_seeds=SEEDS).as_view(),
        "as_view keyword": _update_view(GUARDED).as_view(pool_seeds=SEEDS),
    }


class TestAnAffordanceConditionReadingASeed:
    @pytest.mark.parametrize("how", ["class attribute", "as_view keyword"])
    def test_is_served_with_the_condition_s_answer_where_the_view_registers_it(
        self, how: str
    ) -> None:
        view = _mounts()[how]
        post = Post.objects.create(title="t")
        status, body = _patch(view, post.pk)
        assert (status, body["published"]) == (200, True)

        _BOARD["frozen"] = True
        assert _patch(view, Post.objects.create(title="u").pk) == (
            409,
            {"detail": "The board is frozen.", "code": "board_frozen"},
        )

    def test_the_as_view_keyword_outranks_the_class_attribute(self) -> None:
        """DRF sets the keyword's value on every instance over the class's, so
        the check reads the one the view will dispatch with."""
        with pytest.raises(ImproperlyConfigured, match="frozen"):
            _update_view(GUARDED, pool_seeds=SEEDS).as_view(pool_seeds=DEFAULT_POOL_SEEDS)

    def test_a_view_hooking_the_service_s_kwargs_is_not_checked_at_as_view(self) -> None:
        """A ``get_service_kwargs`` override exempts the view from the seed
        check, its conditions included, so a seed it does not register is
        met on the first request instead."""
        view = _update_view(GUARDED, get_service_kwargs=lambda self: {}).as_view()
        with pytest.raises(TypeError, match="frozen"):
            _patch(view, Post.objects.create(title="t").pk)

    def test_another_registry_without_the_seed_is_refused_too(self) -> None:
        """The check reads the view's registry, whatever it is, not a fixed one."""
        other = DEFAULT_POOL_SEEDS.extend(tenant=lambda: "t")
        with pytest.raises(ImproperlyConfigured, match="frozen"):
            _update_view(GUARDED).as_view(pool_seeds=other)


class TestAPreconditionReadingASeed:
    def test_is_served_where_the_view_registers_it(self) -> None:
        view = _update_view(PRECONDITIONED, pool_seeds=SEEDS).as_view()
        assert _patch(view, Post.objects.create(title="t").pk)[0] == 200

        _BOARD["frozen"] = True
        status, body = _patch(view, Post.objects.create(title="u").pk)
        assert status == 422
        assert "The board is frozen." in json.dumps(body)

    def test_is_refused_at_as_view_where_the_view_does_not(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="frozen"):
            _update_view(PRECONDITIONED).as_view()


def _frozen_posts(*, frozen: bool) -> QuerySet[Post]:
    return Post.objects.filter(published=frozen)


_RENDERING = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=_BY_PK.selector,
    reads=_BY_PK.reads,
    permissions=_OPEN,
    presenter=SerializerPresenter(PostSerializer),
    affordances={
        "publish": ServiceSpec(service=lambda: None, permissions=_OPEN, affordances=[NOT_FROZEN])
    },
)


class TestASelectorReadingASeed:
    def test_a_list_view_registering_it_serves_the_selector_s_answer(self) -> None:
        Post.objects.create(title="draft")
        Post.objects.create(title="out", published=True)
        spec = SelectorSpec(kind=SelectorKind.LIST, selector=_frozen_posts, permissions=_OPEN)
        view = type(
            "_View",
            (SelectorListView,),
            {"spec": spec, "serializer_class": PostSerializer, "pool_seeds": SEEDS},
        ).as_view()
        assert [row["title"] for row in view(factory.get("/")).data] == ["draft"]
        _BOARD["frozen"] = True
        assert [row["title"] for row in view(factory.get("/")).data] == ["out"]

    def test_a_retrieve_view_registering_it_by_keyword_serves_it(self) -> None:
        post = Post.objects.create(title="t")
        spec = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, pk, frozen: Post.objects.filter(pk=pk, published=frozen).first(),
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
            permissions=_OPEN,
            presenter=SerializerPresenter(PostSerializer),
        )
        view = type("_View", (SelectorRetrieveView,), {"spec": spec}).as_view(pool_seeds=SEEDS)
        assert view(factory.get("/"), pk=str(post.pk)).data["title"] == "t"

    def test_a_retrieve_view_registering_it_renders_an_affordance_s_answer(self) -> None:
        """A selector's affordance answers are asked when the row is presented,
        with the seeds the view registers."""
        post = Post.objects.create(title="t")
        view = type(
            "_View", (SelectorRetrieveView,), {"spec": _RENDERING, "pool_seeds": SEEDS}
        ).as_view()

        def answer() -> Any:
            response = view(factory.get("/"), pk=str(post.pk))
            response.render()
            return json.loads(response.content)["affordances"]["publish"]

        assert answer() == {"available": True}
        _BOARD["frozen"] = True
        assert answer() == {
            "available": False,
            "code": "board_frozen",
            "reason": "The board is frozen.",
        }

    def test_an_affordance_s_answer_needing_a_seed_unregistered_is_refused_at_as_view(
        self,
    ) -> None:
        with pytest.raises(ImproperlyConfigured, match="frozen"):
            type("_View", (SelectorRetrieveView,), {"spec": _RENDERING}).as_view()


class _Case:
    """One standalone view reading the ``frozen`` seed, and the request that serves it."""

    def __init__(self, base: type, spec: Any, request: Any, ok: int, **kwargs: Any) -> None:
        self.base, self.spec, self.request, self.ok, self.kwargs = base, spec, request, ok, kwargs

    def view_class(self, **attrs: Any) -> type:
        extra = {"queryset": Post.objects.all(), "serializer_class": PostSerializer}
        return type("_View", (self.base,), {"spec": self.spec, **extra, **attrs})

    def status(self, view: Any) -> int:
        """The status of the request on a row that exists, on the view just built."""
        pk = str(Post.objects.create(title="t").pk)
        response = view(self.request(), pk=pk) if self.kwargs.get("by_pk") else view(self.request())
        return response.status_code


def _post_by_pk_when_frozen(*, pk: int, frozen: bool) -> Post | None:
    return Post.objects.filter(pk=pk).first()


_BY_PK_READS = Parameters.of(Parameter("pk", "integer", required=True))

# Each standalone view with a spec whose only seed is ``frozen``, read where
# the kernel's check looks: a mutation view's affordance condition, a list or
# retrieve view's selector. The five make every mount site answer for itself.
_STANDALONE = {
    "create": _Case(
        ServiceCreateView,
        ServiceSpec(
            service=lambda: Post.objects.create(title="n"),
            permissions=_OPEN,
            presenter=SerializerPresenter(PostSerializer),
            affordances=[NOT_FROZEN],
        ),
        lambda: factory.post("/", {}, format="json"),
        201,
    ),
    "update": _Case(
        ServiceUpdateView, GUARDED, lambda: factory.patch("/", {}, format="json"), 200, by_pk=True
    ),
    "delete": _Case(
        ServiceDeleteView,
        ServiceSpec(
            service=lambda *, instance: instance.delete(),
            permissions=_OPEN,
            instance_selector_spec=_BY_PK,
            affordances=[NOT_FROZEN],
            allow_none=True,
        ),
        lambda: factory.delete("/"),
        200,
        by_pk=True,
    ),
    "list": _Case(
        SelectorListView,
        SelectorSpec(kind=SelectorKind.LIST, selector=_frozen_posts, permissions=_OPEN),
        lambda: factory.get("/"),
        200,
    ),
    "retrieve": _Case(
        SelectorRetrieveView,
        SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=_post_by_pk_when_frozen,
            reads=_BY_PK_READS,
            permissions=_OPEN,
            presenter=SerializerPresenter(PostSerializer),
        ),
        lambda: factory.get("/"),
        200,
        by_pk=True,
    ),
}


@pytest.mark.parametrize("name", list(_STANDALONE))
class TestEveryStandaloneViewReadingASeed:
    """Each of the five views asks the kernel's seed check at ``as_view()`` against
    the registry it will dispatch with, so a mount site passing the kernel's
    defaults, or ignoring the keyword, fails its own case here."""

    def test_is_refused_at_as_view_naming_the_seed_where_it_is_not_registered(
        self, name: str
    ) -> None:
        with pytest.raises(ImproperlyConfigured, match="frozen"):
            _STANDALONE[name].view_class().as_view()

    @pytest.mark.parametrize("how", ["class attribute", "as_view keyword"])
    def test_is_served_where_the_view_registers_it(self, name: str, how: str) -> None:
        case = _STANDALONE[name]
        if how == "class attribute":
            view = case.view_class(pool_seeds=SEEDS).as_view()
        else:
            view = case.view_class().as_view(pool_seeds=SEEDS)
        assert case.status(view) == case.ok


class TestAViewSetRegisteringASeed:
    def _viewset(self, **attrs: Any) -> type[ServiceViewSet]:
        return type(
            "_ViewSet",
            (ServiceViewSet,),
            {"action_specs": {"partial_update": GUARDED}, "queryset": Post.objects.all(), **attrs},
        )

    def test_its_class_attribute_serves_the_entry(self) -> None:
        view = self._viewset(pool_seeds=SEEDS).as_view({"patch": "partial_update"})
        _BOARD["frozen"] = True
        assert _patch(view, Post.objects.create(title="t").pk)[0] == 409

    def test_its_as_view_keyword_serves_the_entry(self) -> None:
        view = self._viewset().as_view({"patch": "partial_update"}, pool_seeds=SEEDS)
        assert _patch(view, Post.objects.create(title="t").pk)[0] == 200
        _BOARD["frozen"] = True
        assert _patch(view, Post.objects.create(title="u").pk)[0] == 409

    def test_without_it_the_entry_is_refused_at_as_view(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="frozen"):
            self._viewset().as_view({"patch": "partial_update"})


class TestADecoratedAction:
    def test_a_service_action_is_served_with_its_viewset_s_seeds(self) -> None:
        @service_action(GUARDED, detail=True, methods=["patch"])
        def publish(self: Any, request: Any, pk: Any = None) -> None:
            """Stubbed: the decorator serves the spec."""

        viewset = type(
            "_ViewSet",
            (GenericViewSet,),
            {"queryset": Post.objects.all(), "publish": publish, "pool_seeds": SEEDS},
        )
        view = viewset.as_view({"patch": "publish"})
        assert _patch(view, Post.objects.create(title="t").pk)[0] == 200
        _BOARD["frozen"] = True
        assert _patch(view, Post.objects.create(title="u").pk)[0] == 409

    def test_a_service_action_missing_a_seed_mounts_and_fails_its_first_request(self) -> None:
        """On DRF's own ``GenericViewSet`` nothing asks the seed check: its
        ``as_view()`` is DRF's, so the missing seed is the request's
        ``TypeError`` (the docs say so). A viewset built on this package's
        mixins refuses it at ``as_view()`` (test_a_decorated_action_s_seeds)."""

        @service_action(GUARDED, detail=True, methods=["patch"])
        def publish(self: Any, request: Any, pk: Any = None) -> None:
            """Stubbed: the decorator serves the spec."""

        viewset = type(
            "_ViewSet", (GenericViewSet,), {"queryset": Post.objects.all(), "publish": publish}
        )
        view = viewset.as_view({"patch": "publish"})
        with pytest.raises(TypeError, match="frozen"):
            _patch(view, Post.objects.create(title="t").pk)

    def test_a_selector_action_reading_a_seed_its_viewset_registers_is_served(self) -> None:
        spec = SelectorSpec(kind=SelectorKind.LIST, selector=_frozen_posts, permissions=_OPEN)

        @selector_action(spec)
        def posts(self: Any, request: Any) -> None:
            """Stubbed: the decorator serves the spec."""

        viewset = type(
            "_ViewSet",
            (GenericViewSet,),
            {"serializer_class": PostSerializer, "posts": posts, "pool_seeds": SEEDS},
        )
        assert viewset.as_view({"get": "posts"})(factory.get("/")).status_code == 200


class _StampedClass(PermissionCheck):
    """A class-level check opting into the ``stamp`` seed by naming it."""

    def has_permission(self, principal: Any, spec: Any, *, stamp: str) -> bool:
        return stamp == "stamp"


def test_options_asks_a_check_naming_a_seed_with_the_view_s_seeds() -> None:
    seeds = DEFAULT_POOL_SEEDS.extend(stamp=lambda: "stamp")
    view = _update_view(_publish_spec(permissions=(_StampedClass(),)), pool_seeds=seeds).as_view()
    post = Post.objects.create(title="t")
    assert _patch(view, post.pk)[0] == 200
    response = view(factory.options("/"), pk=str(post.pk))
    assert "PUT" in response.data["actions"]


class _CountingResolver:
    """A seed resolver counting its calls."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return "stamp"


class _StampedRow(PermissionCheck):
    """An object-level check opting into the ``stamp`` seed by naming it."""

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True

    def has_object_permission(self, principal: Any, spec: Any, target: Any, *, stamp: str) -> bool:
        return stamp == "stamp"


class TestTheSeedsTheTargetWasCheckedWith:
    def test_are_handed_on_so_a_call_through_the_view_s_lookup_resolves_each_once(self) -> None:
        """The update view's row is found by the kernel's ``resolve_target``, which
        resolves the seeds its checks name; ``dispatch`` runs on those rather
        than resolving them again."""
        resolver = _CountingResolver()
        seeds: PoolSeeds = DEFAULT_POOL_SEEDS.extend(stamp=resolver)
        spec = _publish_spec(permissions=(_StampedRow(),))
        view = _update_view(spec, pool_seeds=seeds).as_view()
        assert _patch(view, Post.objects.create(title="t").pk)[0] == 200
        assert resolver.calls == 1
