"""The value about to be presented, handed to a presenter's serializer context callable.

A ``SerializerPresenter``'s ``serializer_context`` callable may declare the
value it renders under the presenter's ``value_keyword`` (``result`` by
default; ``instance`` or ``page`` where the author names it so), and is handed
it only when declared, so it can run a *single* batched query against the
exact objects and pass the outcome on through the context. A callable
declaring only ``view`` and ``request``, or a subset of them, is unaffected.

The view-side binder, ``_invoke_provider``, is held here too: it is how the
view's own hooks are asked, on either route.

A selector view reaches the presenter, but a list is presented row by row, so a
callable asking for the page is a strict xfail naming what owes it.
"""

from __future__ import annotations

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
from rest_framework.pagination import PageNumberPagination
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorListView, SelectorRetrieveView, ServiceCreateView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.views.utils import _invoke_provider
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)

_A_PAGE_IS_PRESENTED_ROW_BY_ROW = (
    "A kernel SelectorListView presents the page's rows through the spec's SerializerPresenter, "
    "but the presenter inherits the kernel's Presenter.presented_rows, which asks presented() "
    "once per row, so a callable declaring value_keyword='page' is handed one row (len(page) "
    "raises) and never the page's rows together."
)


def _capturing_serializer_factory() -> type[serializers.ModelSerializer]:
    """Fresh subclass per test so the ``captured`` class var is isolated."""

    class _Capturing(serializers.ModelSerializer):
        captured: dict[str, Any] = {}

        class Meta:
            model = Author
            fields = ("id", "name")

        def to_representation(self, instance: Any) -> Any:
            type(self).captured = dict(self.context)
            return super().to_representation(instance)

    return _Capturing


class _SmallPage(PageNumberPagination):
    page_size = 2


class TestInvokeProvider:
    def test_provider_declaring_view_and_request_gets_exactly_those(self) -> None:
        got: dict[str, Any] = {}

        def fn(view: Any, request: Any) -> dict[str, Any]:
            got.update(view=view, request=request)
            return {}

        _invoke_provider(fn, view="V", request="R", extras={"result": "X"})
        assert got == {"view": "V", "request": "R"}

    def test_provider_declaring_only_request(self) -> None:
        got: dict[str, Any] = {}

        def fn(request: Any) -> dict[str, Any]:
            got["request"] = request
            return {}

        _invoke_provider(fn, view="V", request="R", extras={})
        assert got == {"request": "R"}

    def test_declared_extra_is_passed_by_keyword(self) -> None:
        def fn(*, result: Any) -> dict[str, Any]:
            return {"result": result}

        assert _invoke_provider(fn, view="V", request="R", extras={"result": "X"}) == {
            "result": "X"
        }

    def test_var_keyword_provider_receives_the_whole_pool(self) -> None:
        def fn(**kwargs: Any) -> dict[str, Any]:
            return dict(kwargs)

        assert _invoke_provider(fn, view="V", request="R", extras={"result": "X"}) == {
            "view": "V",
            "request": "R",
            "result": "X",
        }


@pytest.mark.django_db
class TestTheResultOfAMutation:
    def test_the_presenter_s_callable_is_handed_the_service_s_result(self) -> None:
        capturing = _capturing_serializer_factory()
        seen: dict[str, Any] = {}
        author = Author.objects.create(name="seed")

        def provider(view: Any, request: Any, *, result: Any) -> dict[str, Any]:
            seen["result"] = result
            return {"result_pk": result.pk}

        class _View(ServiceCreateView):
            spec = ServiceSpec(
                service=lambda: author,
                permissions=_OPEN,
                presenter=SerializerPresenter(capturing, serializer_context=provider),
                atomic=False,
            )

        assert _View.as_view()(factory.post("/", {}, format="json")).status_code == 201
        assert seen["result"] == author
        assert capturing.captured["result_pk"] == author.pk

    def test_the_result_is_the_output_selector_s_row(self) -> None:
        """An output selector re-reads the row, and the callable sees what it read,
        not the service's own return."""
        capturing = _capturing_serializer_factory()
        seen: dict[str, Any] = {}
        raw = Author.objects.create(name="raw")

        def provider(*, result: Any) -> dict[str, Any]:
            seen.update(same_object_as_raw=result is raw, pk=result.pk)
            return {}

        class _View(ServiceCreateView):
            spec = ServiceSpec(
                service=lambda: raw,
                permissions=_OPEN,
                output_selector_spec=SelectorSpec(
                    kind=SelectorKind.RETRIEVE,
                    selector=lambda *, result: Author.objects.get(pk=result.pk),
                ),
                presenter=SerializerPresenter(capturing, serializer_context=provider),
                atomic=False,
            )

        assert _View.as_view()(factory.post("/", {}, format="json")).status_code == 201
        assert seen == {"same_object_as_raw": False, "pk": raw.pk}

    def test_a_callable_declaring_only_view_and_request_is_unaffected(self) -> None:
        capturing = _capturing_serializer_factory()
        author = Author.objects.create(name="seed")

        class _View(ServiceCreateView):
            spec = ServiceSpec(
                service=lambda: author,
                permissions=_OPEN,
                presenter=SerializerPresenter(
                    capturing, serializer_context=lambda view, request: {"plain": True}
                ),
                atomic=False,
            )

        _View.as_view()(factory.post("/", {}, format="json"))
        assert capturing.captured["plain"] is True

    def test_the_view_s_output_hook_is_handed_the_result(self) -> None:
        capturing = _capturing_serializer_factory()

        class _View(ServiceCreateView):
            spec = ServiceSpec(
                service=lambda: Author.objects.create(name="made"),
                permissions=_OPEN,
                presenter=SerializerPresenter(capturing),
                atomic=False,
            )

            def get_output_serializer_context(self, *, result: Any) -> dict[str, Any]:
                return {"hook_pk": result.pk}

        _View.as_view()(factory.post("/", {}, format="json"))
        assert capturing.captured["hook_pk"] == Author.objects.get().pk

    def test_one_batched_query_against_the_result(self, django_assert_num_queries: Any) -> None:
        capturing = _capturing_serializer_factory()

        class _NameIn(serializers.Serializer):
            name = serializers.CharField()

        def provider(*, result: Any) -> dict[str, Any]:
            return {"total": Author.objects.filter(pk=result.pk).count()}

        class _View(ServiceCreateView):
            spec = ServiceSpec(
                service=lambda *, data: Author.objects.create(name=data["name"]),
                permissions=_OPEN,
                validator=SerializerValidator(_NameIn),
                presenter=SerializerPresenter(capturing, serializer_context=provider),
                atomic=False,
            )

        request = factory.post("/", {"name": "Ada"}, format="json")
        # The insert, then the callable's one count.
        with django_assert_num_queries(2):
            _View.as_view()(request)
        assert capturing.captured["total"] == 1


@pytest.mark.django_db
class TestTheRowsOfARead:
    def test_a_retrieve_view_s_callable_is_handed_the_instance(self) -> None:
        capturing = _capturing_serializer_factory()
        author = Author.objects.create(name="Ada")

        class _View(SelectorRetrieveView):
            serializer_class = AuthorSerializer
            spec = SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
                reads=Parameters.of(Parameter("pk", "integer", required=True)),
                permissions=_OPEN,
                presenter=SerializerPresenter(
                    capturing,
                    value_keyword="instance",
                    serializer_context=lambda *, instance: {"instance_pk": instance.pk},
                ),
            )

        _View.as_view()(factory.get("/"), pk=str(author.pk))
        assert capturing.captured["instance_pk"] == author.pk

    @pytest.mark.xfail(strict=True, reason=_A_PAGE_IS_PRESENTED_ROW_BY_ROW)
    def test_a_paginated_list_view_s_callable_is_handed_the_page(self) -> None:
        capturing = _capturing_serializer_factory()
        for name in ("a", "b", "c"):
            Author.objects.create(name=name)

        class _View(SelectorListView):
            serializer_class = AuthorSerializer
            pagination_class = _SmallPage
            spec = SelectorSpec(
                kind=SelectorKind.LIST,
                selector=lambda: Author.objects.order_by("id"),
                permissions=_OPEN,
                presenter=SerializerPresenter(
                    capturing,
                    value_keyword="page",
                    serializer_context=lambda *, page: {"page_size": len(page)},
                ),
            )

        _View.as_view()(factory.get("/"))
        assert capturing.captured["page_size"] == 2
