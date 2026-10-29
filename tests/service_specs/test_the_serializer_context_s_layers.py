"""The serializer context's four layers, on a view serving a kernel spec.

DRF's own context (the view's ``get_serializer_context``), the directional and
per-action view hooks, then the seat's own callable (``SerializerValidator``'s
and ``SerializerPresenter``'s ``serializer_context``), each later layer winning
on a key it shares with an earlier one. Each reaches the input serializer the
kernel validates through and the output serializer it presents through, and
nothing else: no service's pool.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django_service_specs import (
    DEFAULT_POOL_SEEDS,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.present import present
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorListView, SelectorRetrieveView, ServiceCreateView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Post

pytestmark = pytest.mark.django_db

_KEYS = ("base", "shared", "hook_in", "hook_out", "spec_in", "spec_out", "written")
_OPEN = (Unrestricted(),)


class _Out(serializers.Serializer):
    title = serializers.CharField()
    context = serializers.SerializerMethodField()

    def get_context(self, obj: Any) -> dict[str, Any]:
        return {key: self.context[key] for key in _KEYS if key in self.context}


def _create(*, data: Any) -> SimpleNamespace:
    return SimpleNamespace(title=data["title"])


def _spec(
    seen: list[dict[str, Any]],
    *,
    input_context: Any = None,
    output_context: Any = None,
    service: Any = _create,
) -> ServiceSpec:
    class _In(serializers.Serializer):
        title = serializers.CharField()

        def validate(self, attrs: Any) -> Any:
            seen.append({key: self.context[key] for key in _KEYS if key in self.context})
            return attrs

    return ServiceSpec(
        service=service,
        permissions=_OPEN,
        validator=SerializerValidator(_In, serializer_context=input_context),
        presenter=SerializerPresenter(_Out, serializer_context=output_context),
    )


class _View(ServiceCreateView):
    """A view whose ``get_serializer_context`` is the first layer.

    ``get_permissions`` answers the view's own classes, none, as the spine's
    views do: ``MutationFlowMixin``'s reads a drfs-only spec field."""

    permission_classes: Any = []
    authentication_classes: Any = []
    asked = 0

    def get_permissions(self) -> list[Any]:
        return []

    def get_serializer_context(self) -> dict[str, Any]:
        type(self).asked += 1
        return {**super().get_serializer_context(), "base": "view", "shared": "view"}


class _HookedView(_View):
    """The directional hooks, the second and third layers."""

    def get_input_serializer_context(self) -> dict[str, Any]:
        return {"shared": "hook", "hook_in": "in"}

    def get_output_serializer_context(self, result: Any) -> dict[str, Any]:
        return {"shared": "hook", "hook_out": result.title}


def _post(spec: ServiceSpec, view: type[_View] = _View) -> Any:
    view_class = type("_Served", (view,), {"spec": spec, "asked": 0})
    response = view_class.as_view()(APIRequestFactory().post("/", {"title": "hi"}, format="json"))
    assert response.status_code == 201, response.data
    return response.data["context"], view_class


class TestTheViewsOwnContext:
    def test_reaches_the_input_and_the_output_serializer(self) -> None:
        seen: list[dict[str, Any]] = []

        output, _ = _post(_spec(seen))

        assert seen == [{"base": "view", "shared": "view"}]
        assert output == {"base": "view", "shared": "view"}


class TestTheSeatsCallable:
    def test_has_the_final_say_on_the_input(self) -> None:
        seen: list[dict[str, Any]] = []

        _post(_spec(seen, input_context=lambda: {"shared": "spec", "spec_in": 1}))

        assert seen == [{"base": "view", "shared": "spec", "spec_in": 1}]

    def test_has_the_final_say_on_the_output_and_reads_the_result(self) -> None:
        spec = _spec([], output_context=lambda result: {"shared": "spec", "spec_out": result.title})

        output, _ = _post(spec)

        assert output == {"base": "view", "shared": "spec", "spec_out": "hi"}

    def test_an_input_key_is_the_output_s_too_for_both_share_one_dict(self) -> None:
        """Changed by design: drfs gave the input and the output serializer a copy of
        the view's context each, so a key one seat's callable set never reached the
        other. A kernel route builds one context dict per request and hands it to every
        serializer, so the input callable's key is on the output serializer and the
        output callable's key lands on the very dict the input serializer holds."""
        contexts: list[dict[str, Any]] = []

        class _Recording(serializers.Serializer):
            title = serializers.CharField()

            def validate(self, attrs: Any) -> Any:
                contexts.append(self.context)
                return attrs

        spec = ServiceSpec(
            service=_create,
            permissions=_OPEN,
            validator=SerializerValidator(_Recording, serializer_context=lambda: {"spec_in": 1}),
            presenter=SerializerPresenter(_Out, serializer_context=lambda: {"spec_out": 2}),
        )

        output, _ = _post(spec)

        assert output["spec_in"] == 1
        assert output["spec_out"] == 2
        (input_context,) = contexts
        assert (input_context["spec_in"], input_context["spec_out"]) == (1, 2)

    def test_the_input_callable_is_asked_once_per_call_with_the_view_s_request(self) -> None:
        asked: list[bool] = []

        def provider(request: Any, view: Any) -> dict[str, Any]:
            asked.append(view.request is request)
            return {"spec_in": 1}

        _post(_spec([], input_context=provider))

        assert asked == [True]

    def test_a_registered_seed_reaches_both_callables(self) -> None:
        seen: list[dict[str, Any]] = []
        spec = _spec(
            seen,
            input_context=lambda tenant: {"spec_in": tenant},
            output_context=lambda tenant: {"spec_out": tenant},
        )

        result = dispatch(
            spec,
            principal=AnonymousUser(),
            arguments={"title": "hi"},
            pool_seeds=DEFAULT_POOL_SEEDS.extend(tenant=lambda: "acme"),
        )

        assert seen[0]["spec_in"] == "acme"
        assert present(spec, result)["context"]["spec_out"] == "acme"

    def test_a_callable_naming_the_call_context_is_asked_once_with_the_call_s_dict(self) -> None:
        asked: list[Any] = []
        call_context: dict[str, Any] = {"tenant": "acme"}

        def provider(call_context: Any = None) -> dict[str, Any]:
            asked.append(call_context)
            return {"spec_in": "spec"}

        dispatch(
            _spec([], input_context=provider),
            principal=AnonymousUser(),
            arguments={"title": "hi"},
            call_context=call_context,
        )

        assert len(asked) == 1
        assert asked[0] is call_context


def test_no_layer_reaches_a_kwargs_service_s_pool() -> None:
    pools: list[dict[str, Any]] = []

    def service(**pool: Any) -> SimpleNamespace:
        pools.append(pool)
        return SimpleNamespace(title=pool["data"]["title"])

    _post(_spec([], input_context=lambda: {"spec_in": 1}, service=service), _HookedView)

    assert not set(pools[0]).intersection({*_KEYS, "_serializer_context_layers"})


class TestTheViewsHooks:
    """The view's directional hooks, the second and third layers on the one dict."""

    def test_layer_over_the_view_s_own_context_on_the_input(self) -> None:
        seen: list[dict[str, Any]] = []

        _post(_spec(seen), _HookedView)

        assert seen == [{"base": "view", "shared": "hook", "hook_in": "in"}]

    def test_layer_over_the_view_s_own_context_on_the_output_with_the_result(self) -> None:
        """Changed by design: the input hook's key is on the output serializer too.

        drfs built each serializer's context from its own hook alone, so ``hook_in``
        never reached the output; the kernel route's one dict per request carries
        every layer to every serializer."""
        output, _ = _post(_spec([]), _HookedView)

        assert output == {
            "base": "view",
            "shared": "hook",
            "hook_in": "in",
            "hook_out": "hi",
        }

    def test_lie_beneath_the_seat_s_callable(self) -> None:
        seen: list[dict[str, Any]] = []
        spec = _spec(seen, input_context=lambda: {"shared": "spec"})

        output, _ = _post(spec, _HookedView)

        assert seen == [{"base": "view", "shared": "spec", "hook_in": "in"}]
        assert output["hook_out"] == "hi"


class _PostOut(serializers.Serializer):
    title = serializers.CharField()
    context = serializers.SerializerMethodField()

    def get_context(self, obj: Any) -> dict[str, Any]:
        return {key: self.context[key] for key in _KEYS if key in self.context}


class _ContextHook:
    """A selector view whose ``get_serializer_context`` is the view layer, none of the
    directional hooks: a selector view has only the one output serializer."""

    permission_classes: Any = []
    authentication_classes: Any = []

    def get_permissions(self) -> list[Any]:
        return []

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "base": "view", "shared": "view"}  # ty: ignore[unresolved-attribute]


class TestOnASelectorView:
    """A selector view's presenter is handed the view's own context and the seat's
    callable over it: the two layers a selector view has."""

    def _spec(self, kind: SelectorKind, **options: Any) -> SelectorSpec:
        return SelectorSpec(
            kind=kind,
            selector=(
                (lambda: Post.objects.order_by("id").first())
                if kind is SelectorKind.RETRIEVE
                else (lambda: Post.objects.order_by("id"))
            ),
            permissions=_OPEN,
            presenter=SerializerPresenter(_PostOut, **options),
        )

    def test_a_retrieve_view_layers_the_seat_s_callable_over_its_own_context(self) -> None:
        Post.objects.create(title="p")
        spec = self._spec(
            SelectorKind.RETRIEVE, serializer_context=lambda: {"shared": "spec", "spec_out": 1}
        )
        view = type("_Served", (_ContextHook, SelectorRetrieveView), {"spec": spec})

        response = view.as_view()(APIRequestFactory().get("/"))

        assert response.status_code == 200, response.data
        assert response.data["context"] == {"base": "view", "shared": "spec", "spec_out": 1}

    def test_a_list_view_layers_the_seat_s_callable_over_its_own_context(self) -> None:
        Post.objects.create(title="p")
        spec = self._spec(
            SelectorKind.LIST, serializer_context=lambda: {"shared": "spec", "spec_out": 1}
        )
        view = type("_Served", (_ContextHook, SelectorListView), {"spec": spec})

        response = view.as_view()(APIRequestFactory().get("/"))

        assert response.status_code == 200, response.data
        (row,) = response.data
        assert row["context"] == {"base": "view", "shared": "spec", "spec_out": 1}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "the serializer context is not yet the call's one dict: call_base_context hands "
        "each serializer its own copy of the view's get_serializer_context(), so a key "
        "the input serializer's validate() writes reaches neither the service's "
        "call_context nor the output serializer"
    ),
)
def test_one_dict_per_request_reaches_both_serializers_and_the_service() -> None:
    """A key the input serializer's ``validate()`` writes is the output's and the service's.

    The inversion of drfs' per-serializer copy: the context the input
    serializer is built under is the dict the view's ``get_serializer_context()``
    returned, the one dict of the request.
    """
    written: list[Any] = []
    contexts: list[Any] = []

    class _Writing(serializers.Serializer):
        title = serializers.CharField()

        def validate(self, attrs: Any) -> Any:
            contexts.append(self.context)
            self.context["written"] = "by validate"
            return attrs

    class _Returning(_View):
        def get_serializer_context(self) -> dict[str, Any]:
            context = super().get_serializer_context()
            contexts.append(context)
            return context

    def service(*, data: Any, call_context: dict[str, Any]) -> SimpleNamespace:
        written.append(call_context.get("written"))
        return SimpleNamespace(title=data["title"])

    spec = ServiceSpec(
        service=service,
        permissions=_OPEN,
        validator=SerializerValidator(_Writing),
        presenter=SerializerPresenter(_Out),
    )

    output, _ = _post(spec, _Returning)

    assert written == ["by validate"]
    assert output["written"] == "by validate"
    returned, validated = contexts[:2]
    assert validated is returned
