"""What ``as_view()`` and ``@service_action`` refuse of a ``DiscriminatedAction``.

Each refusal asserts its own sentence, so a tree refusing the entry for being
no spec at all fails here rather than passing by accident.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import (
    DEFAULT_POOL_SEEDS,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.routers import SimpleRouter
from rest_framework.test import APIRequestFactory

from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.types.discriminated_action import DiscriminatedAction
from django_spec_rest.views.mutation.service_create_view import ServiceCreateView
from django_spec_rest.views.mutation.service_delete_view import ServiceDeleteView
from django_spec_rest.views.mutation.service_update_view import ServiceUpdateView
from django_spec_rest.views.query.selector_list_view import SelectorListView
from django_spec_rest.views.query.selector_retrieve_view import SelectorRetrieveView
from django_spec_rest.viewsets.decorators.service_action import service_action
from django_spec_rest.viewsets.selector_viewset import SelectorViewSet
from django_spec_rest.viewsets.service_viewset import ServiceViewSet

_OPEN = (Unrestricted(),)
factory = APIRequestFactory()


class _NameIn(serializers.Serializer):
    name = serializers.CharField()


_BY_PK = Parameters.of(Parameter("pk", "integer", required=True))


def _row(reads: Parameters = _BY_PK) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.RETRIEVE, selector=lambda **kwargs: None, reads=reads)


def _create() -> ServiceSpec:
    return ServiceSpec(service=lambda: None, permissions=_OPEN)


def _on_a_row(reads: Parameters = _BY_PK) -> ServiceSpec:
    return ServiceSpec(
        service=lambda *, instance: None, permissions=_OPEN, instance_selector_spec=_row(reads)
    )


def _choose() -> str:
    return "a"


def _action(**specs: Any) -> DiscriminatedAction:
    return DiscriminatedAction(_choose, specs or {"a": _create()})


def _mount(entry: Any, *, key: str = "create", **attrs: Any) -> Any:
    viewset = type("_ViewSet", (ServiceViewSet,), {"action_specs": {key: entry}, **attrs})
    return viewset.as_view({"post": key})


def _decorate(action: Any, **kwargs: Any) -> Any:
    @service_action(action, methods=["post"], **kwargs)
    def run(self: Any, request: Any) -> None:
        """Stubbed."""

    return run


class TestWhereItAttaches:
    @pytest.mark.parametrize("key", ["create", "update", "partial_update", "destroy"])
    def test_under_each_write_action_it_mounts(self, key: str) -> None:
        variant = _create() if key == "create" else _on_a_row()
        assert _mount(_action(a=variant), key=key) is not None

    @pytest.mark.parametrize("key", ["list", "retrieve", "publish"])
    def test_under_any_other_key_it_is_refused_naming_the_key(self, key: str) -> None:
        with pytest.raises(
            ImproperlyConfigured, match=rf"action_specs\['{key}'\].*@service_action"
        ):
            _mount(_action(), key=key)

    def test_on_a_selector_viewset_it_is_refused_too(self) -> None:
        viewset = type("_ViewSet", (SelectorViewSet,), {"action_specs": {"list": _action()}})
        with pytest.raises(ImproperlyConfigured, match="serves a write action"):
            viewset.as_view({"get": "list"})

    def test_an_action_specs_keyword_is_asked_as_the_class_attribute_is(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="serves a write action"):
            ServiceViewSet.as_view({"get": "list"}, action_specs={"list": _action()})

    @pytest.mark.parametrize(
        "base",
        [
            ServiceCreateView,
            ServiceUpdateView,
            ServiceDeleteView,
            SelectorListView,
            SelectorRetrieveView,
        ],
    )
    def test_as_a_standalone_view_s_spec_it_is_refused_saying_where_it_goes(
        self, base: type
    ) -> None:
        view = type("_View", (base,), {"spec": _action()})
        with pytest.raises(ImproperlyConfigured, match=r"DiscriminatedAction.*action_specs"):
            view.as_view()


# What the shape of the wrapper refuses, whichever door it comes through.
SHAPES = {
    "no variants": (lambda: DiscriminatedAction(_choose, {}), "no variants"),
    "not a mapping": (lambda: DiscriminatedAction(_choose, [_create()]), "must map"),  # ty: ignore
    "a key that is no str": (
        lambda: DiscriminatedAction(_choose, {1: _create()}),  # ty: ignore
        r"\[1\]",
    ),
    "a None variant": (
        lambda: DiscriminatedAction(_choose, {"a": None}),  # ty: ignore
        r"\['a'\].*None",
    ),
    "no callable": (lambda: DiscriminatedAction("a", {"a": _create()}), "must be a callable"),  # ty: ignore
    "async": (
        lambda: DiscriminatedAction(_async_choose, {"a": _create()}),
        "async",
    ),
    "an async __call__": (
        lambda: DiscriminatedAction(_AsyncCall(), {"a": _create()}),
        "async",
    ),
    "a positional-only parameter": (
        lambda: DiscriminatedAction(_positional, {"a": _create()}),
        "position only",
    ),
    "a required name outside the pool": (
        lambda: DiscriminatedAction(_needs_tenant, {"a": _create()}),
        r"\['tenant'\]",
    ),
    "an optional name outside the pool": (
        lambda: DiscriminatedAction(_maybe_tenant, {"a": _create()}),
        r"\['tenant'\]",
    ),
}


async def _async_choose() -> str:
    return "a"


class _AsyncCall:
    async def __call__(self) -> str:
        return "a"


def _positional(request: Any, /) -> str:
    return "a"


def _needs_tenant(*, tenant: Any) -> str:
    return "a"


def _maybe_tenant(*, tenant: Any = None) -> str:
    return "a"


class TestTheShape:
    @pytest.mark.parametrize("case", SHAPES)
    def test_as_view_refuses_it(self, case: str) -> None:
        build, sentence = SHAPES[case]
        with pytest.raises(ImproperlyConfigured, match=sentence) as refusal:
            _mount(build())
        assert "action_specs['create']" in str(refusal.value)

    @pytest.mark.parametrize("case", SHAPES)
    def test_the_decorator_refuses_it(self, case: str) -> None:
        build, sentence = SHAPES[case]
        with pytest.raises(ImproperlyConfigured, match=sentence) as refusal:
            _decorate(build())
        assert "@service_action" in str(refusal.value)

    @pytest.mark.parametrize(
        "discriminator",
        [
            lambda: "a",
            lambda *, request: "a",
            lambda *, request, data, user, view, call_context: "a",
            lambda **kwargs: "a",
            lambda *args, **kwargs: "a",
        ],
    )
    def test_a_discriminator_declaring_only_pool_names_mounts(self, discriminator: Any) -> None:
        assert _mount(DiscriminatedAction(discriminator, {"a": _create()})) is not None
        assert _decorate(DiscriminatedAction(discriminator, {"a": _create()})) is not None

    def test_a_positional_only_parameter_with_a_default_is_left_to_it(self) -> None:
        def choose(fallback: str = "a", /) -> str:
            return fallback

        assert _mount(DiscriminatedAction(choose, {"a": _create()})) is not None


def _no_seed(*, tenant: Any) -> None: ...


NOT_SPECS = {
    "a selector spec": lambda: _row(),
    "no spec at all": lambda: "create_it",
    "another wrapper": lambda: _action(),
}


class TestEachVariantIsAskedAsAPlainEntry:
    @pytest.mark.parametrize("case", NOT_SPECS)
    def test_one_that_is_no_service_spec_is_refused_labelled(self, case: str) -> None:
        action = _action(bad=NOT_SPECS[case]())
        with pytest.raises(ImproperlyConfigured, match=r"\['bad'\]"):
            _mount(action)
        with pytest.raises(ImproperlyConfigured, match=r"\['bad'\]"):
            _decorate(action)

    def test_one_naming_no_target_under_a_detail_action_is_refused_labelled(self) -> None:
        action = _action(fine=_on_a_row(), bare=_create())
        with pytest.raises(ImproperlyConfigured, match=r"\['bare'\].*no target selector"):
            _mount(action, key="update")

    def test_one_naming_no_target_on_a_detail_service_action_is_refused_labelled(self) -> None:
        action = _action(fine=_on_a_row(), bare=_create())
        with pytest.raises(ImproperlyConfigured, match=r"\['bare'\].*no target selector"):
            _decorate(action, detail=True)

    def test_one_over_a_list_body_needs_no_target_under_a_detail_action(self) -> None:
        many = ServiceSpec(
            service=lambda *, data: None,
            permissions=_OPEN,
            validator=SerializerValidator(_NameIn),
            many=True,
            atomic=False,
        )
        assert _mount(_action(a=many), key="partial_update") is not None

    def test_a_keyword_nothing_fills_is_refused_labelled(self) -> None:
        bad = ServiceSpec(service=_no_seed, permissions=_OPEN)
        with pytest.raises(ImproperlyConfigured, match=r"\['bad'\]: .*tenant"):
            _mount(_action(fine=_create(), bad=bad))

    def test_a_plain_entry_s_seed_refusal_keeps_the_kernel_s_sentence(self) -> None:
        bad = ServiceSpec(service=_no_seed, permissions=_OPEN)
        with pytest.raises(ImproperlyConfigured) as refusal:
            _mount(bad)
        assert "_ViewSet" not in str(refusal.value)

    def test_a_seed_the_view_registers_fills_it_where_the_default_does_not(self) -> None:
        bad = ServiceSpec(service=_no_seed, permissions=_OPEN)
        seeds = DEFAULT_POOL_SEEDS.extend(tenant=lambda: "t")
        assert _mount(_action(a=bad), pool_seeds=seeds) is not None

    def test_a_service_kwargs_hook_excuses_a_variant_as_it_does_a_plain_entry(self) -> None:
        bad = ServiceSpec(service=_no_seed, permissions=_OPEN)
        attrs = {"get_service_kwargs": lambda self: {"tenant": "t"}}
        assert _mount(_action(a=bad), **attrs) is not None


class TestADecoratedActionsSeeds:
    def test_are_asked_of_each_variant_at_the_viewset_s_as_view_labelled(self) -> None:
        bad = ServiceSpec(service=_no_seed, permissions=_OPEN)

        class _ViewSet(ServiceViewSet):
            @service_action(_action(fine=_create(), bad=bad), methods=["post"])
            def run(self, request: Any) -> None:
                """Stubbed."""

        with pytest.raises(ImproperlyConfigured, match=r"_ViewSet\.run\['bad'\]: .*tenant"):
            _ViewSet.as_view({"post": "run"})

    def test_a_seed_the_viewset_registers_serves(self) -> None:
        bad = ServiceSpec(service=_no_seed, permissions=_OPEN)

        class _ViewSet(ServiceViewSet):
            pool_seeds = DEFAULT_POOL_SEEDS.extend(tenant=lambda: "t")

            @service_action(_action(a=bad), methods=["post"])
            def run(self, request: Any) -> None:
                """Stubbed."""

        assert _ViewSet.as_view({"post": "run"}) is not None

    def test_a_hook_that_may_fill_the_keyword_excuses_every_variant(self) -> None:
        bad = ServiceSpec(service=_no_seed, permissions=_OPEN)

        class _ViewSet(ServiceViewSet):
            def get_service_kwargs(self) -> dict[str, Any]:
                return {"tenant": "t"}

            @service_action(_action(a=bad), methods=["post"])
            def run(self, request: Any) -> None:
                """Stubbed."""

        assert _ViewSet.as_view({"post": "run"}) is not None


class TestALookupCapture:
    """``_mapped_specs``: a router's capture is asked of each variant's own row lookup."""

    @staticmethod
    def _routed(entry: Any, *, decorated: bool = False) -> None:
        router = SimpleRouter()
        if decorated:

            class _ViewSet(ServiceViewSet):
                @service_action(entry, detail=True, methods=["post"])
                def run(self, request: Any, pk: Any) -> None:
                    """Stubbed."""

        else:

            class _ViewSet(ServiceViewSet):
                action_specs = {"update": entry}

        router.register("things", _ViewSet, basename="thing")
        assert router.urls

    @pytest.mark.parametrize("decorated", [False, True])
    def test_a_variant_whose_lookup_misses_it_is_refused_labelled(self, decorated: bool) -> None:
        other = Parameters.of(Parameter("slug", "string", required=True))
        action = _action(fine=_on_a_row(), bad=_on_a_row(other))
        with pytest.raises(ImproperlyConfigured, match=r"\['bad'\].*'pk'"):
            self._routed(action, decorated=decorated)

    def test_every_variant_reading_it_mounts(self) -> None:
        self._routed(_action(a=_on_a_row(), b=_on_a_row()))

    def test_a_variant_over_a_list_body_has_no_lookup_to_miss(self) -> None:
        many = ServiceSpec(
            service=lambda *, data: None,
            permissions=_OPEN,
            validator=SerializerValidator(_NameIn),
            many=True,
            atomic=False,
        )
        self._routed(_action(a=_on_a_row(), b=many))
