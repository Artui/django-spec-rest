"""A kernel spec's view's ``success_status`` as a callable (upsert 200/201).

A kernel ``ServiceSpec`` has no ``success_status``, which is HTTP's alone, so
its view declares it (``MutationFlowMixin.success_status``). Driven through the
standalone views; the viewsets' ``action_specs`` and ``@service_action`` read it
as their own lane decides.
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

from django_spec_rest import ServiceCreateView, ServiceUpdateView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _AuthorIn(serializers.Serializer):
    name = serializers.CharField()


@dataclass
class _UpsertResult:
    author: Author
    created: bool


def _upsert_author(*, data: dict[str, Any]) -> _UpsertResult:
    author, created = Author.objects.get_or_create(name=data["name"])
    return _UpsertResult(author=author, created=created)


def _refetch(*, result: _UpsertResult) -> Author:
    return Author.objects.get(pk=result.author.pk)


def _upsert_status(*, result: _UpsertResult) -> int:
    # 201 for a freshly created row, 200 for an existing one: keyed on the
    # *service's* return value, not the re-read output row.
    return 201 if result.created else 200


class _UpsertView(ServiceCreateView):
    success_status = _upsert_status
    spec = ServiceSpec(
        service=_upsert_author,
        permissions=_OPEN,
        validator=SerializerValidator(_AuthorIn),
        output_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=_refetch,
            permissions=_OPEN,
            presenter=SerializerPresenter(AuthorSerializer),
        ),
    )


def _archive(*, instance: Author) -> None:
    # In place, returning nothing: an empty body, under the callable's status.
    instance.name = f"[archived] {instance.name}"
    instance.save(update_fields=["name"])


def _archive_status(*, instance: Author, view: Any, request: Any) -> int:
    assert view.request is request
    return 205


def _author(*, pk: int) -> Author | None:
    return Author.objects.filter(pk=pk).first()


_AUTHOR = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=_author,
    reads=Parameters.of(Parameter("pk", "integer")),
    permissions=_OPEN,
)


class _ArchiveView(ServiceUpdateView):
    success_status = _archive_status
    spec = ServiceSpec(service=_archive, permissions=_OPEN, instance_selector_spec=_AUTHOR)


class TestCallableSuccessStatus:
    def test_create_returns_201_then_200_on_upsert(self) -> None:
        view = _UpsertView.as_view()

        first = view(factory.post("/", {"name": "Ada"}, format="json"))
        assert first.status_code == 201
        assert first.data["name"] == "Ada"

        # Same name again: get_or_create finds the row, so 200 and no duplicate.
        second = view(factory.post("/", {"name": "Ada"}, format="json"))
        assert second.status_code == 200
        assert Author.objects.filter(name="Ada").count() == 1

    def test_a_callable_status_applies_to_an_empty_answer(self) -> None:
        """Resolved per request from the pool, ``instance`` the row the view
        found; with nothing to present, the set status still applies rather
        than the ``204`` an unset one falls back to."""
        author = Author.objects.create(name="Grace")
        response = _ArchiveView.as_view()(factory.put("/", {}, format="json"), pk=author.pk)
        assert response.status_code == 205
        assert not response.data
        author.refresh_from_db()
        assert author.name == "[archived] Grace"

    def test_an_int_status_resolving_to_204_answers_200_with_a_body(self) -> None:
        """A ``204`` carries no body, so a value to present goes out under ``200``."""
        view = type("_View", (_UpsertView,), {"success_status": 204}).as_view()
        response = view(factory.post("/", {"name": "Ada"}, format="json"))
        assert response.status_code == 200
        assert response.data["name"] == "Ada"
