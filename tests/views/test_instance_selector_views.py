"""A kernel ``ServiceSpec``'s ``instance_selector_spec`` on the standalone mutation views.

The spec carries the lookup, so the views need no ``queryset``. Its row is
found by the kernel's dispatch from the route's declared capture; a
``filter_set`` on the lookup narrows which row a mutation may reach.
"""

from __future__ import annotations

from typing import Any

import django_filters
import pytest
from django.core.exceptions import ImproperlyConfigured
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

from django_spec_rest import ServiceDeleteView, ServiceUpdateView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_PK = Parameters.of(Parameter("pk", "integer", required=True))


class _AuthorIn(serializers.Serializer):
    name = serializers.CharField(max_length=20)


def _author_by_pk(*, pk: int) -> QuerySet[Author]:
    return Author.objects.filter(pk=pk)


def _update_author(*, instance: Author, data: dict[str, Any]) -> Author:
    instance.name = data["name"]
    instance.save(update_fields=["name"])
    return instance


def _delete_author(*, instance: Author) -> None:
    instance.delete()


def _lookup(**fields: Any) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE, selector=_author_by_pk, reads=_PK, permissions=_OPEN, **fields
    )


def _update_spec(**lookup: Any) -> ServiceSpec:
    return ServiceSpec(
        service=_update_author,
        permissions=_OPEN,
        validator=SerializerValidator(_AuthorIn),
        instance_selector_spec=_lookup(**lookup),
        presenter=SerializerPresenter(AuthorSerializer),
    )


class _StandIn:
    """``get_permissions`` stands in for ``MutationFlowMixin``'s, which reads a
    drfs spec's ``permission_classes``, as the spine's views do."""

    permission_classes: Any

    def get_permissions(self) -> list[Any]:
        return [permission() for permission in self.permission_classes]


def _view(base: type, spec: ServiceSpec) -> Any:
    return type("_View", (_StandIn, base), {"spec": spec}).as_view()


@pytest.fixture
def author() -> Author:
    return Author.objects.create(name="orig")


class TestTheSpecCarriesTheLookup:
    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_an_update_view_needs_no_queryset(self, author: Author, method: str) -> None:
        request = getattr(factory, method)("/", {"name": "new"}, format="json")
        response = _view(ServiceUpdateView, _update_spec())(request, pk=str(author.pk))
        assert response.status_code == 200, response.data
        assert response.data == {"id": author.pk, "name": "new"}

    def test_a_delete_view_needs_no_queryset(self, author: Author) -> None:
        spec = ServiceSpec(
            service=_delete_author, permissions=_OPEN, instance_selector_spec=_lookup()
        )
        response = _view(ServiceDeleteView, spec)(factory.delete("/"), pk=str(author.pk))
        assert response.status_code == 204
        assert not Author.objects.filter(pk=author.pk).exists()

    def test_a_missing_row_is_404(self) -> None:
        request = factory.put("/", {"name": "new"}, format="json")
        assert _view(ServiceUpdateView, _update_spec())(request, pk="999").status_code == 404

    def test_a_json_array_body_is_a_400_not_a_500(self, author: Author) -> None:
        request = factory.patch("/", [1, 2], format="json")
        response = _view(ServiceUpdateView, _update_spec())(request, pk=str(author.pk))
        assert response.status_code == 400
        author.refresh_from_db()
        assert author.name == "orig"

    def test_a_list_lookup_is_refused_when_the_spec_is_built(self) -> None:
        with pytest.raises(ImproperlyConfigured):
            ServiceSpec(
                service=_update_author,
                permissions=_OPEN,
                instance_selector_spec=SelectorSpec(
                    kind=SelectorKind.LIST, selector=_author_by_pk, permissions=_OPEN
                ),
            )


class _ByName(django_filters.FilterSet):
    scope = django_filters.CharFilter(field_name="name")

    class Meta:
        model = Author
        fields: list[str] = []


class TestALookupsFilterSet:
    @pytest.mark.xfail(
        strict=True,
        reason="kernel_arguments reads a service spec's body and route alone, so the query "
        "string never reaches its lookup's filter_set; an ask on dispatch/kernel_edge.py",
    )
    def test_the_query_string_is_the_scope(self, author: Author) -> None:
        request = factory.patch("/?scope=someone-else", {"name": "new"}, format="json")
        response = _view(ServiceUpdateView, _update_spec(filter_set=_ByName))(
            request, pk=str(author.pk)
        )
        assert response.status_code == 404

    def test_what_the_body_sends_for_the_filter(self, author: Author) -> None:
        """The kernel has one argument namespace, so a body key named like
        the lookup's filter is that filter's value: the client's body sets
        the scope a mutation may reach, where drfs read it off the query
        string alone. Recorded here as the answer served today."""
        request = factory.patch("/", {"name": "new", "scope": "someone-else"}, format="json")
        response = _view(ServiceUpdateView, _update_spec(filter_set=_ByName))(
            request, pk=str(author.pk)
        )
        assert response.status_code == 404
