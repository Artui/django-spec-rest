"""A kernel spec's serializer context callable runs once per request, on every view path.

The seats' ``serializer_context`` callables are documented as the place for one
batched query against the data being serialized, so a second run is a second
query, and a run per row is N of them. Each path is driven over HTTP with a
counting callable. A list is presented with the whole set under one context,
never row by row, so a list of two rows still counts one.

A kernel spec's presenter asks its context once per row: a selector list view
pins that answer, and each other test that meets it is a strict xfail naming what
owes it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.db.models import QuerySet
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

from django_spec_rest import SelectorListView, ServiceCreateView, ServiceUpdateView, ServiceViewSet
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


_A_CONTEXT_PER_ROW = (
    "SerializerPresenter (service_specs/serializer_presenter.py) inherits the kernel's "
    "Presenter.presented_rows, which asks presented() once per row, so its serializer_context "
    "callable runs once per row rather than once for the list."
)


def _counter() -> tuple[list[int], Callable[..., dict[str, Any]]]:
    calls: list[int] = []

    def context() -> dict[str, Any]:
        calls.append(1)
        return {"counted": True}

    return calls, context


class _NameIn(serializers.Serializer[Any]):
    name = serializers.CharField()


def _authors() -> QuerySet[Author]:
    return Author.objects.order_by("id")


def _create(*, data: dict[str, Any]) -> Author:
    return Author.objects.create(name=data["name"])


def _create_many(*, data: list[dict[str, Any]]) -> list[Author]:
    return [Author.objects.create(name=row["name"]) for row in data]


def _touch_all(*, collection: QuerySet[Author]) -> QuerySet[Author]:
    return collection


def _view(base: type, spec: ServiceSpec) -> Any:
    return type("_View", (base,), {"spec": spec}).as_view()


@pytest.fixture
def two_authors() -> list[Author]:
    return [Author.objects.create(name="a"), Author.objects.create(name="b")]


def test_a_create_view_presents_under_one_context() -> None:
    calls, context = _counter()
    spec = ServiceSpec(
        service=_create,
        permissions=_OPEN,
        validator=SerializerValidator(_NameIn),
        presenter=SerializerPresenter(AuthorSerializer, serializer_context=context),
    )
    response = _view(ServiceCreateView, spec)(factory.post("/", {"name": "n"}, format="json"))
    assert response.status_code == 201
    assert len(calls) == 1


def test_a_create_view_validates_under_one_context() -> None:
    calls, context = _counter()
    spec = ServiceSpec(
        service=_create,
        permissions=_OPEN,
        validator=SerializerValidator(_NameIn, serializer_context=context),
        presenter=SerializerPresenter(AuthorSerializer),
    )
    response = _view(ServiceCreateView, spec)(factory.post("/", {"name": "n"}, format="json"))
    assert response.status_code == 201
    assert len(calls) == 1


@pytest.mark.xfail(strict=True, reason=_A_CONTEXT_PER_ROW)
def test_a_many_create_presents_its_rows_under_one_context() -> None:
    calls, context = _counter()
    spec = ServiceSpec(
        service=_create_many,
        permissions=_OPEN,
        many=True,
        atomic=False,
        validator=SerializerValidator(_NameIn),
        presenter=SerializerPresenter(AuthorSerializer, serializer_context=context),
    )
    response = _view(ServiceCreateView, spec)(
        factory.post("/", [{"name": "a"}, {"name": "b"}], format="json")
    )
    assert response.status_code == 201
    assert [row["name"] for row in response.data] == ["a", "b"]
    assert len(calls) == 1


def test_a_many_create_validates_its_rows_under_one_context() -> None:
    calls, context = _counter()
    spec = ServiceSpec(
        service=_create_many,
        permissions=_OPEN,
        many=True,
        atomic=False,
        validator=SerializerValidator(_NameIn, serializer_context=context),
        presenter=SerializerPresenter(AuthorSerializer),
    )
    response = _view(ServiceCreateView, spec)(
        factory.post("/", [{"name": "a"}, {"name": "b"}], format="json")
    )
    assert response.status_code == 201
    assert len(calls) == 1


@pytest.mark.xfail(strict=True, reason=_A_CONTEXT_PER_ROW)
def test_a_collection_update_presents_its_set_under_one_context(
    two_authors: list[Author],
) -> None:
    calls, context = _counter()
    spec = ServiceSpec(
        service=_touch_all,
        permissions=_OPEN,
        collection_selector_spec=SelectorSpec(
            kind=SelectorKind.LIST, selector=_authors, permissions=_OPEN
        ),
        presenter=SerializerPresenter(AuthorSerializer, serializer_context=context),
        returns_many=True,
        atomic=False,
    )
    response = _view(ServiceUpdateView, spec)(factory.put("/"))
    assert response.status_code == 200
    assert len(response.data) == 2
    assert len(calls) == 1


def test_a_selector_list_view_presents_each_row_under_a_context_of_its_own(
    two_authors: list[Author],
) -> None:
    """The decided answer: a list is presented row by row, one context for each.

    The view presents the page's rows through the spec's presenter, and
    ``SerializerPresenter`` inherits the kernel's ``Presenter.presented_rows``,
    which asks ``presented()`` once per row, so the ``serializer_context`` callable
    runs once per row (two rows, two runs) rather than once for the list.
    """
    calls, context = _counter()

    class _View(SelectorListView):
        serializer_class = AuthorSerializer
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=_authors,
            permissions=_OPEN,
            presenter=SerializerPresenter(AuthorSerializer, serializer_context=context),
        )

    response = _View.as_view()(factory.get("/"))
    assert response.status_code == 200
    assert len(calls) == 2


def test_an_update_viewset_action_presents_under_one_context(two_authors: list[Author]) -> None:
    calls, context = _counter()

    def rename(*, instance: Author, data: dict[str, Any]) -> Author:
        instance.name = data["name"]
        instance.save(update_fields=["name"])
        return instance

    class _View(ServiceViewSet):
        queryset = Author.objects.all()
        serializer_class = AuthorSerializer
        action_specs = {
            "update": ServiceSpec(
                service=rename,
                permissions=_OPEN,
                instance_selector_spec=SelectorSpec(
                    kind=SelectorKind.RETRIEVE,
                    selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
                    reads=Parameters.of(Parameter("pk", "integer", required=True)),
                ),
                validator=SerializerValidator(_NameIn),
                presenter=SerializerPresenter(AuthorSerializer, serializer_context=context),
            )
        }

        def get_permissions(self) -> list[Any]:
            return []

    response = _View.as_view({"put": "update"})(
        factory.put("/", {"name": "n"}, format="json"), pk=two_authors[0].pk
    )
    assert response.status_code == 200
    assert len(calls) == 1
