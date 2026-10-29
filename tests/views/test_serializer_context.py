"""The serializer context a view's kernel spec validates and presents under, over HTTP.

A kernel spec's serializers are its seats', ``SerializerValidator`` and
``SerializerPresenter``, and each is built under the context DRF builds on
HTTP: the view's ``get_serializer_context()`` (``request``, ``view``,
``format`` and whatever an override adds), then the view's directional and
per-action hooks, then the seat's own ``serializer_context``, later winning.

The call's context is DRF's serializer context: one dict per request, the very
object every serializer of the call is handed. So a key one layer writes is
there for every later serializer of the call, and the drfs path's "does not
leak into output" answers invert by design; those tests assert the new answer.

What the kernel route does not carry yet is a strict xfail naming the file
that owes it:

- the view's hook chains (``resolve_view_hooks``) reach no kernel call: the
  kernel branch of ``dispatch_mutation_for_spec`` resolves none, and
  ``dispatch_kernel_spec`` sets no ``view_hooks`` on the edge's call state;
- each serializer is still handed its own copy of the context
  (``call_base_context`` and ``base_serializer_context``);
- the kernel selector views render through ``serializer_class``, not the
  spec's presenter;
- a viewset's ``action_specs`` and ``@selector_action`` refuse a kernel spec
  when the view is built.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import (
    SelectorListView,
    SelectorRetrieveView,
    ServiceCreateView,
    ServiceUpdateView,
    ServiceViewSet,
    selector_action,
)
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)

_NO_VIEW_HOOKS = (
    "The view's hook chains reach no kernel call: the kernel branch of "
    "dispatch_mutation_for_spec (views/mutation/utils.py) resolves no resolve_view_hooks, "
    "and dispatch_kernel_spec (dispatch/kernel_edge.py) sets no view_hooks on EdgeCallState."
)
_A_COPY_PER_SERIALIZER = (
    "Each serializer is handed its own copy of the context: call_base_context "
    "(service_specs/utils.py) returns dict(held[2]) / dict(context), and "
    "base_serializer_context returns dict(getter())."
)
_SELECTOR_VIEWS_SKIP_THE_PRESENTER = (
    "A kernel SelectorListView / SelectorRetrieveView renders through serializer_class "
    "(views/query/**), so the spec's SerializerPresenter and its serializer_context never run."
)
_VIEWSETS_REFUSE_A_KERNEL_SPEC = (
    "viewsets/utils.py _validate_action_spec and viewsets/decorators read drfs fields, "
    "so a kernel spec in action_specs or @selector_action is refused at as_view(); "
    "once accepted, the view's hook chains must reach the kernel call too."
)


class _CapturingIn(serializers.Serializer):
    """Records the context its ``validate()`` runs under, as a snapshot."""

    name = serializers.CharField()
    captured: dict[str, Any] = {}

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        type(self).captured = dict(self.context)
        return attrs


class _CapturingOut(serializers.ModelSerializer):
    captured: dict[str, Any] = {}

    class Meta:
        model = Author
        fields = ("id", "name")

    def to_representation(self, instance: Any) -> Any:
        type(self).captured = dict(self.context)
        return super().to_representation(instance)


@pytest.fixture(autouse=True)
def _reset_capture() -> None:
    _CapturingIn.captured = {}
    _CapturingOut.captured = {}


def _create_author(*, data: dict[str, Any]) -> Author:
    return Author.objects.create(name=data["name"])


def _update_author(*, instance: Author, data: dict[str, Any]) -> Author:
    instance.name = data["name"]
    instance.save(update_fields=["name"])
    return instance


def _spec(
    *,
    service: Any = _create_author,
    validator: Any = None,
    presenter: Any = None,
    **extra: Any,
) -> ServiceSpec:
    return ServiceSpec(
        service=service,
        permissions=_OPEN,
        validator=SerializerValidator(_CapturingIn) if validator is None else validator,
        presenter=SerializerPresenter(_CapturingOut) if presenter is None else presenter,
        atomic=False,
        **extra,
    )


class _KernelCreateView(ServiceCreateView):
    """``get_permissions`` answers the view's own classes, as for a spec setting none.

    ``MutationFlowMixin.get_permissions`` reads ``spec.permission_classes``,
    which a kernel spec has no attribute for.
    """

    def get_permissions(self) -> list[Any]:
        return [permission() for permission in self.permission_classes]


def _create(view: type[ServiceCreateView], body: dict[str, Any] | None = None) -> Any:
    sent = {"name": "Ada"} if body is None else body
    return view.as_view()(factory.post("/", sent, format="json"))


class TestTheInputSerializer:
    def test_is_built_under_drf_s_default_context(self) -> None:
        class _View(_KernelCreateView):
            spec = _spec()

        assert _create(_View).status_code == 201
        captured = _CapturingIn.captured
        assert {"request", "view", "format"} <= captured.keys()
        assert isinstance(captured["view"], _View)

    def test_the_view_s_get_serializer_context_flows_in(self) -> None:
        class _View(_KernelCreateView):
            spec = _spec()

            def get_serializer_context(self) -> dict[str, Any]:
                return {**super().get_serializer_context(), "tenant": "acme"}

        _create(_View)
        assert _CapturingIn.captured["tenant"] == "acme"

    @pytest.mark.xfail(strict=True, reason=_NO_VIEW_HOOKS)
    def test_the_directional_hook_layers_over_drf_s(self) -> None:
        class _View(_KernelCreateView):
            spec = _spec()

            def get_input_serializer_context(self) -> dict[str, Any]:
                return {**super().get_input_serializer_context(), "origin": "input"}

        _create(_View)
        assert _CapturingIn.captured["origin"] == "input"

    @pytest.mark.xfail(strict=True, reason=f"{_NO_VIEW_HOOKS} {_A_COPY_PER_SERIALIZER}")
    def test_the_directional_hook_s_key_is_there_for_the_output(self) -> None:
        """The context being one dict per request, the input hook's key reaches the
        output serializer after it: the drfs path's "does not leak into output"
        inverts by design."""

        class _View(_KernelCreateView):
            spec = _spec()

            def get_input_serializer_context(self) -> dict[str, Any]:
                return {**super().get_input_serializer_context(), "origin": "input"}

        _create(_View)
        assert _CapturingOut.captured["origin"] == "input"

    def test_a_dataclass_validator_s_serializer_is_built_under_it(self) -> None:
        """The serializer a dataclass input is wrapped in carries the context too,
        read here off the bound serializer the service is handed."""

        @dataclass
        class _Payload:
            name: str

        seen: dict[str, Any] = {}

        def service(*, data: _Payload, serializer: Any) -> None:
            seen.update(serializer.context)

        class _View(_KernelCreateView):
            spec = ServiceSpec(
                service=service,
                permissions=_OPEN,
                validator=SerializerValidator(
                    _Payload, serializer_context=lambda: {"marker": "dataclass"}
                ),
                atomic=False,
            )

            def get_serializer_context(self) -> dict[str, Any]:
                return {**super().get_serializer_context(), "tenant": "acme"}

        assert _create(_View).status_code == 204
        assert seen["marker"] == "dataclass"
        assert seen["tenant"] == "acme"
        assert isinstance(seen["view"], _View)


class TestTheOutputSerializer:
    def test_is_built_under_drf_s_default_context(self) -> None:
        class _View(_KernelCreateView):
            spec = _spec()

        _create(_View)
        assert {"request", "view", "format"} <= _CapturingOut.captured.keys()
        assert isinstance(_CapturingOut.captured["view"], _View)

    @pytest.mark.xfail(strict=True, reason=_NO_VIEW_HOOKS)
    def test_the_directional_hook_layers_over_drf_s_and_never_reaches_the_input(self) -> None:
        """The output hook runs after validation, so its key is in the one dict
        only once the input serializer has validated."""

        class _View(_KernelCreateView):
            spec = _spec()

            def get_output_serializer_context(self) -> dict[str, Any]:
                return {**super().get_output_serializer_context(), "origin": "output"}

        _create(_View)
        assert _CapturingOut.captured["origin"] == "output"
        assert "origin" not in _CapturingIn.captured

    def test_a_spec_with_no_presenter_renders_its_value(self) -> None:
        class _View(_KernelCreateView):
            spec = ServiceSpec(service=lambda: {"raw": True}, permissions=_OPEN, atomic=False)

        response = _create(_View, {})
        assert response.status_code == 201
        assert response.data == {"raw": True}


class TestPerActionHooks:
    @pytest.mark.xfail(strict=True, reason=_NO_VIEW_HOOKS)
    def test_a_standalone_view_has_no_action_so_only_its_directional_hook_runs(self) -> None:
        author = Author.objects.create(name="orig")

        class _View(ServiceUpdateView):
            spec = _spec(
                service=_update_author,
                instance_selector_spec=SelectorSpec(
                    kind=SelectorKind.RETRIEVE,
                    selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
                    reads=Parameters.of(Parameter("pk", "integer", required=True)),
                    permissions=_OPEN,
                ),
            )

            def get_permissions(self) -> list[Any]:
                return [permission() for permission in self.permission_classes]

            def get_input_serializer_context(self) -> dict[str, Any]:
                return {"directional": "input"}

            def get_update_input_serializer_context(self) -> dict[str, Any]:
                return {"per_action": "update-input"}

        response = _View.as_view()(factory.put("/", {"name": "new"}, format="json"), pk=author.pk)
        assert response.status_code == 200
        assert _CapturingIn.captured["directional"] == "input"
        assert "per_action" not in _CapturingIn.captured
        assert getattr(_CapturingIn.captured["view"], "action", None) is None

    @pytest.mark.xfail(strict=True, reason=_VIEWSETS_REFUSE_A_KERNEL_SPEC)
    def test_a_viewset_s_per_action_hook_layers_on_its_own_action(self) -> None:
        class _ViewSet(ServiceViewSet):
            queryset = Author.objects.all()
            action_specs = {"create": _spec()}

            def get_permissions(self) -> list[Any]:
                return []

            def get_create_input_serializer_context(self) -> dict[str, Any]:
                return {"per_action": "create-input"}

        _ViewSet.as_view({"post": "create"})(factory.post("/", {"name": "Ada"}, format="json"))
        assert _CapturingIn.captured["per_action"] == "create-input"


class TestTheSeatsOwnContext:
    def test_the_validator_s_context_is_applied(self) -> None:
        class _View(_KernelCreateView):
            spec = _spec(
                validator=SerializerValidator(
                    _CapturingIn, serializer_context=lambda: {"spec_key": "input"}
                )
            )

        _create(_View)
        assert _CapturingIn.captured["spec_key"] == "input"

    @pytest.mark.xfail(strict=True, reason=_A_COPY_PER_SERIALIZER)
    def test_the_validator_s_context_is_there_for_the_output(self) -> None:
        """One dict per request: the input seat's key reaches the output
        serializer, where the drfs path held it to the input."""

        class _View(_KernelCreateView):
            spec = _spec(
                validator=SerializerValidator(
                    _CapturingIn, serializer_context=lambda: {"input_only": True}
                )
            )

        _create(_View)
        assert _CapturingIn.captured["input_only"] is True
        assert _CapturingOut.captured["input_only"] is True

    @pytest.mark.xfail(strict=True, reason=_NO_VIEW_HOOKS)
    def test_the_validator_s_context_wins_over_the_view_s_hook(self) -> None:
        class _View(_KernelCreateView):
            spec = _spec(
                validator=SerializerValidator(
                    _CapturingIn, serializer_context=lambda: {"layer": "spec"}
                )
            )

            def get_input_serializer_context(self) -> dict[str, Any]:
                return {"layer": "view", "view_only": True}

        _create(_View)
        assert _CapturingIn.captured["layer"] == "spec"
        assert _CapturingIn.captured["view_only"] is True

    def test_the_validator_s_context_callable_is_handed_the_view_and_the_request(self) -> None:
        seen: dict[str, Any] = {}

        def provider(view: Any, request: Any) -> dict[str, Any]:
            seen.update(view=view, request=request)
            return {}

        class _View(_KernelCreateView):
            spec = _spec(validator=SerializerValidator(_CapturingIn, serializer_context=provider))

        _create(_View)
        assert isinstance(seen["view"], _View)
        assert seen["request"] is _CapturingIn.captured["request"]

    def test_the_presenter_s_context_is_applied(self) -> None:
        class _View(_KernelCreateView):
            spec = _spec(
                presenter=SerializerPresenter(
                    _CapturingOut, serializer_context=lambda: {"spec_key": "output"}
                )
            )

        _create(_View)
        assert _CapturingOut.captured["spec_key"] == "output"
        assert "spec_key" not in _CapturingIn.captured

    @pytest.mark.xfail(strict=True, reason=_NO_VIEW_HOOKS)
    def test_the_presenter_s_context_wins_over_the_view_s_hook(self) -> None:
        class _View(_KernelCreateView):
            spec = _spec(
                presenter=SerializerPresenter(
                    _CapturingOut, serializer_context=lambda: {"layer": "spec"}
                )
            )

            def get_output_serializer_context(self) -> dict[str, Any]:
                return {"layer": "view", "view_only": True}

        _create(_View)
        assert _CapturingOut.captured["layer"] == "spec"
        assert _CapturingOut.captured["view_only"] is True


def _listed() -> Any:
    return Author.objects.order_by("id")


class TestASelectorView:
    @pytest.mark.xfail(strict=True, reason=_SELECTOR_VIEWS_SKIP_THE_PRESENTER)
    def test_a_list_view_presents_under_its_presenter_s_context(self) -> None:
        Author.objects.create(name="x")

        class _View(SelectorListView):
            serializer_class = AuthorSerializer
            spec = SelectorSpec(
                kind=SelectorKind.LIST,
                selector=_listed,
                permissions=_OPEN,
                presenter=SerializerPresenter(
                    _CapturingOut, serializer_context=lambda: {"spec_key": "list"}
                ),
            )

        _View.as_view()(factory.get("/"))
        assert _CapturingOut.captured["spec_key"] == "list"

    @pytest.mark.xfail(strict=True, reason=_SELECTOR_VIEWS_SKIP_THE_PRESENTER)
    def test_a_retrieve_view_presents_under_its_presenter_s_context(self) -> None:
        author = Author.objects.create(name="x")

        class _View(SelectorRetrieveView):
            serializer_class = AuthorSerializer
            spec = SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
                reads=Parameters.of(Parameter("pk", "integer", required=True)),
                permissions=_OPEN,
                presenter=SerializerPresenter(
                    _CapturingOut, serializer_context=lambda: {"spec_key": "retrieve"}
                ),
            )

        _View.as_view()(factory.get("/"), pk=str(author.pk))
        assert _CapturingOut.captured["spec_key"] == "retrieve"

    @pytest.mark.xfail(strict=True, reason=_VIEWSETS_REFUSE_A_KERNEL_SPEC)
    def test_a_selector_action_presents_under_its_own_hook(self) -> None:
        Author.objects.create(name="x")

        class _View(GenericViewSet):
            serializer_class = AuthorSerializer
            queryset = Author.objects.all()

            @selector_action(
                SelectorSpec(
                    kind=SelectorKind.LIST,
                    selector=_listed,
                    permissions=_OPEN,
                    presenter=SerializerPresenter(_CapturingOut),
                )
            )
            def active(self, request: Any) -> Any:
                """Stubbed: the decorator serves the spec."""

            def get_active_output_serializer_context(self) -> dict[str, Any]:
                return {"per_action": "active"}

        _View.as_view({"get": "active"})(factory.get("/"))
        assert _CapturingOut.captured["per_action"] == "active"
