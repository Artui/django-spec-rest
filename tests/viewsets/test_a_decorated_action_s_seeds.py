"""A decorated action's seeds: checked against its viewset's ``pool_seeds`` at ``as_view()``.

``@service_action`` and ``@selector_action`` run before their viewset exists,
so the seed check is the viewset's: ``as_view()`` on any viewset built on this
package's mixins asks each decorated method's spec against the seeds the
viewset dispatches with. A seed it registers serves; one nobody registers is
refused there, naming the seed, rather than answering each request with a
``TypeError``. Each class is built outside ``pytest.raises`` and only
``as_view()`` inside it, so a refusal at decoration does not pass for one at
mount.
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
    SelectorKind,
    SelectorSpec,
    ServiceError,
    ServiceSpec,
    Unrestricted,
)
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import (
    ActionSerializerResolver,
    SelectorViewSet,
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


def _frozen_posts(*, frozen: bool) -> QuerySet[Post]:
    return Post.objects.filter(published=frozen).order_by("id")


_BY_PK = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, pk: Post.objects.filter(pk=pk).first(),
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
)


def _publish_spec(**fields: Any) -> ServiceSpec:
    return ServiceSpec(
        service=_publish,
        permissions=_OPEN,
        instance_selector_spec=_BY_PK,
        presenter=SerializerPresenter(PostSerializer),
        **fields,
    )


_NOT_FROZEN = Affordance(
    code="board_frozen", reason="The board is frozen.", when=lambda *, frozen: not frozen
)
_SERVICES = {
    "condition": _publish_spec(affordances=[_NOT_FROZEN]),
    "precondition": _publish_spec(preconditions=[_refuse_when_frozen]),
}
_FROZEN_POSTS = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=_frozen_posts,
    permissions=_OPEN,
    presenter=SerializerPresenter(PostSerializer),
)

_SEATS = pytest.mark.parametrize("seat", sorted(_SERVICES))
# Both of this package's viewset roots: one carrying the mutation hooks, one not.
_BASES = pytest.mark.parametrize(
    "base", [ServiceViewSet, SelectorViewSet], ids=lambda b: b.__name__
)
_HOW = pytest.mark.parametrize("how", ["class attribute", "as_view keyword"])


def _with_service(spec: ServiceSpec, base: type, **attrs: Any) -> Any:
    @service_action(spec, detail=True, methods=["patch"])
    def publish(self: Any, request: Any, pk: Any = None) -> None:
        """Stubbed: the decorator serves the spec."""

    return type("_ViewSet", (base,), {"queryset": Post.objects.all(), "publish": publish, **attrs})


def _with_selector(base: type, **attrs: Any) -> Any:
    @selector_action(_FROZEN_POSTS)
    def posts(self: Any, request: Any) -> None:
        """Stubbed: the decorator serves the spec."""

    return type("_ViewSet", (base,), {"queryset": Post.objects.all(), "posts": posts, **attrs})


def _mount(viewset: Any, actions: dict[str, str], how: str) -> Any:
    if how == "class attribute":
        return type("_Seeded", (viewset,), {"pool_seeds": SEEDS}).as_view(actions)
    return viewset.as_view(actions, pool_seeds=SEEDS)


def _patch(view: Any, pk: int) -> tuple[int, Any]:
    response = view(factory.patch("/", {}, format="json"), pk=str(pk))
    response.render()
    return response.status_code, json.loads(response.content)


class TestAServiceAction:
    @_BASES
    @_SEATS
    def test_needing_a_seed_its_viewset_does_not_register_is_refused_at_as_view(
        self, seat: str, base: type
    ) -> None:
        viewset = _with_service(_SERVICES[seat], base)
        with pytest.raises(ImproperlyConfigured, match="frozen"):
            viewset.as_view({"patch": "publish"})

    def test_on_a_resolver_over_drf_s_viewset_it_is_refused_too(self) -> None:
        """No mutation mixin, so no ``get_service_kwargs`` to fill the keyword."""
        viewset = _with_service(
            _SERVICES["condition"], type("_R", (ActionSerializerResolver, GenericViewSet), {})
        )
        with pytest.raises(ImproperlyConfigured, match="frozen"):
            viewset.as_view({"patch": "publish"})

    @_BASES
    @_SEATS
    @_HOW
    def test_needing_a_seed_its_viewset_registers_is_served(
        self, how: str, seat: str, base: type
    ) -> None:
        view = _mount(_with_service(_SERVICES[seat], base), {"patch": "publish"}, how)
        status, body = _patch(view, Post.objects.create(title="t").pk)
        assert (status, body["published"]) == (200, True)

        _BOARD["frozen"] = True
        status, body = _patch(view, Post.objects.create(title="u").pk)
        assert (status, body["detail"]) == (
            409 if seat == "condition" else 422,
            "The board is frozen.",
        )

    def test_a_catch_all_hook_filling_the_keyword_mounts_and_fills_it(self) -> None:
        """A hook's keys reach the service's pool, which ``check_seeds`` cannot
        see, so a hooked viewset is not asked it, as a standalone view is not."""
        viewset = _with_service(
            _SERVICES["precondition"],
            ServiceViewSet,
            get_service_kwargs=lambda self: {"frozen": True},
        )
        view = viewset.as_view({"patch": "publish"})
        assert _patch(view, Post.objects.create(title="t").pk)[1]["detail"] == (
            "The board is frozen."
        )

    def test_a_per_action_hook_filling_the_keyword_mounts_and_fills_it(self) -> None:
        viewset = _with_service(
            _SERVICES["precondition"],
            SelectorViewSet,
            get_publish_service_kwargs=lambda self: {"frozen": True},
        )
        view = viewset.as_view({"patch": "publish"})
        assert _patch(view, Post.objects.create(title="t").pk)[1]["detail"] == (
            "The board is frozen."
        )


class TestASelectorAction:
    @_BASES
    def test_reading_a_seed_its_viewset_does_not_register_is_refused_at_as_view(
        self, base: type
    ) -> None:
        viewset = _with_selector(base)
        with pytest.raises(ImproperlyConfigured, match="frozen"):
            viewset.as_view({"get": "posts"})

    @_BASES
    @_HOW
    def test_reading_a_seed_its_viewset_registers_is_served(self, how: str, base: type) -> None:
        draft = Post.objects.create(title="draft")
        published = Post.objects.create(title="out", published=True)
        view = _mount(_with_selector(base), {"get": "posts"}, how)
        assert [row["id"] for row in view(factory.get("/")).data] == [draft.pk]

        _BOARD["frozen"] = True
        assert [row["id"] for row in view(factory.get("/")).data] == [published.pk]

    def test_a_service_kwargs_hook_does_not_excuse_it(self) -> None:
        """The edge hands a kernel selector no view hook, so a viewset's
        service-kwargs hook fills nothing it reads."""
        viewset = _with_selector(ServiceViewSet, get_service_kwargs=lambda self: {"frozen": True})
        with pytest.raises(ImproperlyConfigured, match="frozen"):
            viewset.as_view({"get": "posts"})
