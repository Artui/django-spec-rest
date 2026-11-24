from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import Parameter, Parameters, SelectorKind, SelectorSpec, Unrestricted
from django_service_specs.dispatch.dispatch_result import DispatchResult
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.test import APIRequestFactory

from django_spec_rest import (
    SelectorListView,
    SelectorRetrieveView,
    SelectorViewSet,
    ServiceViewSet,
    selector_action,
)
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.views.utils import with_output_hooks
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


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
    _CapturingOut.captured = {}


def _listed() -> Any:
    return Author.objects.order_by("id")


def _found(*, pk: int) -> Any:
    return Author.objects.filter(pk=pk).first()


def _list_spec(*, presented: bool, **presenter: Any) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=_listed,
        permissions=_OPEN,
        presenter=SerializerPresenter(_CapturingOut, **presenter) if presented else None,
    )


def _retrieve_spec(*, presented: bool, **presenter: Any) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=_found,
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
        permissions=_OPEN,
        presenter=SerializerPresenter(_CapturingOut, **presenter) if presented else None,
    )


class _Hooked(SelectorViewSet):
    serializer_class = _CapturingOut

    def get_output_serializer_context(self) -> dict[str, Any]:
        return {"wide": "view", "layer": "view"}

    def get_list_output_serializer_context(self) -> dict[str, Any]:
        return {"per_action": "list", "layer": "list"}

    def get_retrieve_output_serializer_context(self) -> dict[str, Any]:
        return {"per_action": "retrieve", "layer": "retrieve"}


@pytest.mark.parametrize("presented", [True, False], ids=["presenter", "no-presenter"])
class TestASelectorViewSet:
    def test_its_list_layers_both_hooks_per_action_winning(self, presented: bool) -> None:
        Author.objects.create(name="x")

        class _ViewSet(_Hooked):
            action_specs = {"list": _list_spec(presented=presented)}

        _ViewSet.as_view({"get": "list"})(factory.get("/"))
        captured = _CapturingOut.captured
        assert (captured["wide"], captured["per_action"], captured["layer"]) == (
            "view",
            "list",
            "list",
        )
        assert "request" in captured

    def test_its_retrieve_layers_both_hooks_per_action_winning(self, presented: bool) -> None:
        author = Author.objects.create(name="x")

        class _ViewSet(_Hooked):
            action_specs = {"retrieve": _retrieve_spec(presented=presented)}

        _ViewSet.as_view({"get": "retrieve"})(factory.get("/"), pk=str(author.pk))
        captured = _CapturingOut.captured
        assert (captured["wide"], captured["per_action"], captured["layer"]) == (
            "view",
            "retrieve",
            "retrieve",
        )
        assert "request" in captured

    def test_a_list_hook_is_offered_the_page_and_the_result(self, presented: bool) -> None:
        Author.objects.create(name="a")
        Author.objects.create(name="b")
        Author.objects.create(name="c")
        offered: list[dict[str, Any]] = []

        class _Pages(PageNumberPagination):
            page_size = 2

        class _ViewSet(SelectorViewSet):
            serializer_class = _CapturingOut
            pagination_class = _Pages
            action_specs = {"list": _list_spec(presented=presented)}

            def get_list_output_serializer_context(self, page: Any, result: Any) -> dict[str, Any]:
                offered.append({"page": page, "result": result})
                return {}

        _ViewSet.as_view({"get": "list"})(factory.get("/"))
        assert len(offered) == 1
        assert offered[0]["page"] is offered[0]["result"]
        assert [author.name for author in offered[0]["page"]] == ["a", "b"]

    def test_a_retrieve_hook_is_offered_the_instance_and_the_result(self, presented: bool) -> None:
        author = Author.objects.create(name="x")
        offered: dict[str, Any] = {}

        class _ViewSet(SelectorViewSet):
            serializer_class = _CapturingOut
            action_specs = {"retrieve": _retrieve_spec(presented=presented)}

            def get_output_serializer_context(self, instance: Any, result: Any) -> dict[str, Any]:
                offered.update(instance=instance, result=result)
                return {}

        _ViewSet.as_view({"get": "retrieve"})(factory.get("/"), pk=str(author.pk))
        assert offered["instance"] == author
        assert offered["result"] is offered["instance"]


class TestThePresenterSContext:
    def test_it_is_the_outermost_layer_over_both_hooks(self) -> None:
        Author.objects.create(name="x")

        class _ViewSet(_Hooked):
            action_specs = {
                "list": _list_spec(presented=True, serializer_context=lambda: {"layer": "spec"})
            }

        _ViewSet.as_view({"get": "list"})(factory.get("/"))
        assert (_CapturingOut.captured["layer"], _CapturingOut.captured["per_action"]) == (
            "spec",
            "list",
        )


@pytest.mark.parametrize("presented", [True, False], ids=["presenter", "no-presenter"])
class TestAStandaloneSelectorView:
    def test_a_list_view_honours_its_view_wide_hook(self, presented: bool) -> None:
        Author.objects.create(name="x")

        class _View(SelectorListView):
            serializer_class = _CapturingOut
            spec = _list_spec(presented=presented)

            def get_output_serializer_context(self) -> dict[str, Any]:
                return {"wide": "list-view"}

        _View.as_view()(factory.get("/"))
        assert _CapturingOut.captured["wide"] == "list-view"

    def test_a_retrieve_view_honours_its_view_wide_hook(self, presented: bool) -> None:
        author = Author.objects.create(name="x")

        class _View(SelectorRetrieveView):
            serializer_class = _CapturingOut
            spec = _retrieve_spec(presented=presented)

            def get_output_serializer_context(self) -> dict[str, Any]:
                return {"wide": "retrieve-view"}

        _View.as_view()(factory.get("/"), pk=str(author.pk))
        assert _CapturingOut.captured["wide"] == "retrieve-view"


class TestASelectorAction:
    def test_a_retrieve_action_layers_its_own_hook(self) -> None:
        author = Author.objects.create(name="x")

        class _ViewSet(SelectorViewSet):
            serializer_class = _CapturingOut

            @selector_action(_retrieve_spec(presented=True), detail=True)
            def latest(self, request: Any, pk: Any = None) -> Any:
                """Stubbed: the decorator serves the spec."""

            def get_latest_output_serializer_context(self, instance: Any) -> dict[str, Any]:
                return {"per_action": "latest", "instance": instance}

        _ViewSet.as_view({"get": "latest"})(factory.get("/"), pk=str(author.pk))
        assert _CapturingOut.captured["per_action"] == "latest"
        assert _CapturingOut.captured["instance"] == author


class TestAServiceViewSet:
    def test_its_view_wide_output_hook_reaches_list(self) -> None:
        Author.objects.create(name="x")

        class _ViewSet(ServiceViewSet):
            serializer_class = _CapturingOut
            queryset = Author.objects.all()
            action_specs = {"list": _list_spec(presented=False)}

            def get_permissions(self) -> list[Any]:
                return []

            def get_output_serializer_context(self) -> dict[str, Any]:
                return {**super().get_output_serializer_context(), "wide": "service"}

        _ViewSet.as_view({"get": "list"})(factory.get("/"))
        assert _CapturingOut.captured["wide"] == "service"

    def test_its_kwargs_hooks_never_reach_a_list_selector(self) -> None:
        """Mutation-guarded: the old tree passes it too, as it passed a selector no hooks."""
        seen: dict[str, Any] = {}

        def selector(**kwargs: Any) -> Any:
            seen.update(kwargs)
            return Author.objects.none()

        class _ViewSet(ServiceViewSet):
            serializer_class = _CapturingOut
            queryset = Author.objects.all()
            action_specs = {
                "list": SelectorSpec(kind=SelectorKind.LIST, selector=selector, permissions=_OPEN)
            }

            def get_permissions(self) -> list[Any]:
                return []

            def get_service_kwargs(self) -> dict[str, Any]:
                return {"leaked": "view-wide"}

            def get_list_service_kwargs(self) -> dict[str, Any]:
                return {"leaked_list": "per-action"}

        response = _ViewSet.as_view({"get": "list"})(factory.get("/"))
        assert response.status_code == 200
        assert "leaked" not in seen
        assert "leaked_list" not in seen


def test_a_result_with_no_call_to_present_for_is_left_as_it_is() -> None:
    result = DispatchResult(kind="list", value=[])
    assert with_output_hooks(result, object(), extras=dict) is result


class TestAnUnpaginatedList:
    @pytest.mark.parametrize("presented", [True, False], ids=["presenter", "no-presenter"])
    def test_its_hook_is_offered_a_list_at_no_extra_query(
        self, presented: bool, django_assert_num_queries: Any
    ) -> None:
        Author.objects.create(name="a")
        Author.objects.create(name="b")
        offered: dict[str, Any] = {}

        class _ViewSet(SelectorViewSet):
            serializer_class = _CapturingOut
            action_specs = {"list": _list_spec(presented=presented)}

            def get_list_output_serializer_context(self, page: Any, result: Any) -> dict[str, Any]:
                offered.update(page=page, result=result)
                return {}

        with django_assert_num_queries(1):
            response = _ViewSet.as_view({"get": "list"})(factory.get("/"))
        assert [row["name"] for row in response.data] == ["a", "b"]
        assert isinstance(offered["page"], list)
        assert offered["page"] is offered["result"]
        assert [author.name for author in offered["page"]] == ["a", "b"]

    def test_a_selector_action_s_hook_is_offered_a_list(self) -> None:
        Author.objects.create(name="a")
        offered: dict[str, Any] = {}

        class _ViewSet(SelectorViewSet):
            serializer_class = _CapturingOut

            @selector_action(_list_spec(presented=True))
            def active(self, request: Any) -> Any:
                """Stubbed: the decorator serves the spec."""

            def get_active_output_serializer_context(self, page: Any) -> dict[str, Any]:
                offered.update(page=page)
                return {}

        _ViewSet.as_view({"get": "active"})(factory.get("/"))
        assert isinstance(offered["page"], list)


class _NameOut(serializers.Serializer):
    name = serializers.CharField()


def _streamed() -> Any:
    return ({"name": name} for name in ("a", "b"))


class TestAListOverAOneShotIterable:
    @pytest.mark.parametrize("hooked", [True, False], ids=["hook", "no-hook"])
    @pytest.mark.parametrize("presented", [True, False], ids=["presenter", "no-presenter"])
    def test_its_rows_reach_the_body_and_the_hook(self, presented: bool, hooked: bool) -> None:
        offered: dict[str, Any] = {}

        class _ViewSet(SelectorViewSet):
            serializer_class = _NameOut
            action_specs = {
                "list": SelectorSpec(
                    kind=SelectorKind.LIST,
                    selector=_streamed,
                    permissions=_OPEN,
                    presenter=SerializerPresenter(_NameOut) if presented else None,
                )
            }

            if hooked:

                def get_list_output_serializer_context(self, page: Any) -> dict[str, Any]:
                    offered["page"] = page
                    return {}

        response = _ViewSet.as_view({"get": "list"})(factory.get("/"))
        assert [row["name"] for row in response.data] == ["a", "b"]
        if hooked:
            assert offered["page"] == [{"name": "a"}, {"name": "b"}]
