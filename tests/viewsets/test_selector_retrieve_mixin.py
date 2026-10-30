"""``SelectorRetrieveMixin`` alone over ``GenericViewSet``, with a kernel ``SelectorSpec``."""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    Unrestricted,
)
from rest_framework.decorators import action
from rest_framework.filters import BaseFilterBackend
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import SelectorRetrieveMixin
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()


def _retrieve(**fields: Any) -> SelectorSpec:
    defaults: dict[str, Any] = {
        "selector": lambda *, pk: Author.objects.filter(pk=pk).first(),
        "reads": Parameters.of(Parameter("pk", "integer", required=True)),
        "permissions": (Unrestricted(),),
        "presenter": SerializerPresenter(AuthorSerializer),
    }
    return SelectorSpec(kind=SelectorKind.RETRIEVE, **{**defaults, **fields})


class _ExcludeEverything(BaseFilterBackend):
    def filter_queryset(self, request: Any, queryset: Any, view: Any) -> Any:
        return queryset.none()


def _viewset(**attrs: Any) -> Any:
    base = (SelectorRetrieveMixin, GenericViewSet)
    return type("_ViewSet", base, {"queryset": Author.objects.all(), **attrs})


def _get(viewset: Any, action_name: str = "retrieve", **kwargs: Any) -> Response:
    return viewset.as_view({"get": action_name})(factory.get("/"), **kwargs)


def test_the_row_is_presented_by_the_spec() -> None:
    author = Author.objects.create(name="a")
    response = _get(_viewset(action_specs={"retrieve": _retrieve()}), pk=author.pk)
    assert response.data == {"id": author.pk, "name": "a"}


def test_an_allow_none_miss_serves_a_json_null_body() -> None:
    response = _get(_viewset(action_specs={"retrieve": _retrieve(allow_none=True)}), pk=999)
    response.render()
    assert response.status_code == 200
    assert response.content == b"null"
    assert response["Content-Type"] == "application/json"


def test_filter_backends_do_not_narrow_the_lookup() -> None:
    """As on the drfs path: the selector is the lookup, and DRF's
    ``filter_queryset()`` runs only inside its own ``get_object()``."""
    author = Author.objects.create(name="a")
    viewset = _viewset(action_specs={"retrieve": _retrieve()}, filter_backends=[_ExcludeEverything])
    assert _get(viewset, pk=author.pk).status_code == 200


def test_the_view_s_object_permission_is_asked_of_the_row() -> None:
    author = Author.objects.create(name="a")

    class _NoRows(BasePermission):
        def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
            return False

    viewset = _viewset(action_specs={"retrieve": _retrieve()}, permission_classes=[_NoRows])
    assert _get(viewset, pk=author.pk).status_code == 403


def test_get_object_answers_the_kernel_spec_s_row() -> None:
    """A detail handler of the view's own reading ``get_object()`` gets the
    row the retrieve spec finds, as on the drfs path."""
    author = Author.objects.create(name="a")
    Author.objects.create(name="b")

    class _ViewSet(SelectorRetrieveMixin, GenericViewSet):
        queryset = Author.objects.none()
        action_specs = {"retrieve": _retrieve()}

        @action(detail=True)
        def label(self, request: Any, pk: Any = None) -> Response:
            return Response(self.get_object().name)

    assert _get(_ViewSet, "label", pk=author.pk).data == "a"
