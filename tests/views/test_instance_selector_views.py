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
    UnknownArguments,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceDeleteView, ServiceUpdateView
from django_spec_rest.dispatch import kernel_edge
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


class _ScopeIsMine(BasePermission):
    """Admits a request whose query string says ``?scope=mine``: the guard a
    body-supplied scope walks past."""

    def has_permission(self, request: Any, view: Any) -> bool:
        return request.query_params.get("scope") == "mine"


class TestALookupsFilterSet:
    """The lookup's filter reads the route and the query string, never the body."""

    def test_the_query_string_is_the_scope(self, author: Author) -> None:
        request = factory.patch("/?scope=someone-else", {"name": "new"}, format="json")
        response = _view(ServiceUpdateView, _update_spec(filter_set=_ByName))(
            request, pk=str(author.pk)
        )
        assert response.status_code == 404

    def test_the_query_string_s_scope_finds_its_row(self, author: Author) -> None:
        request = factory.patch("/?scope=orig", {"name": "new"}, format="json")
        response = _view(ServiceUpdateView, _update_spec(filter_set=_ByName))(
            request, pk=str(author.pk)
        )
        assert response.status_code == 200, response.data
        author.refresh_from_db()
        assert author.name == "new"

    @pytest.mark.parametrize("fmt", ["json", "multipart"])
    def test_what_the_body_sends_for_the_filter(self, fmt: str) -> None:
        """The kernel has one argument namespace, so a body key named like the
        lookup's filter would be that filter's value, and the client's body
        would pick the row a write reaches past a permission that checks
        ``?scope``. The edge drops it, so ``?scope=mine`` finds no row (404)
        and the victim's row is unchanged."""
        victim = Author.objects.create(name="victim")
        view = type(
            "_View",
            (_StandIn, ServiceUpdateView),
            {
                "spec": _update_spec(filter_set=_ByName),
                "permission_classes": [_ScopeIsMine],
            },
        ).as_view()
        request = factory.patch("/?scope=mine", {"name": "pwned", "scope": "victim"}, format=fmt)
        response = view(request, pk=str(victim.pk))
        assert response.status_code == 404
        victim.refresh_from_db()
        assert victim.name == "victim"

    @pytest.mark.parametrize("fmt", ["json", "multipart"])
    def test_a_body_s_filter_key_alone_scopes_nothing(self, author: Author, fmt: str) -> None:
        """With no ``?scope``, a body's ``scope`` is no filter value at all: the
        row the route names is the one found, whatever the body says the scope
        is. Read off the body, ``nobody`` would have found no row."""
        request = factory.patch("/", {"name": "new", "scope": "nobody"}, format=fmt)
        response = _view(ServiceUpdateView, _update_spec(filter_set=_ByName))(
            request, pk=str(author.pk)
        )
        assert response.status_code == 200, response.data
        author.refresh_from_db()
        assert author.name == "new"

    def test_the_rest_of_a_write_s_query_string_is_no_argument(self, author: Author) -> None:
        """Only the filter's keys are read off a write's query string: ``?format``
        and any other key there are DRF's, never an unknown argument."""
        request = factory.patch("/?scope=orig&format=json&page=2", {"name": "new"}, format="json")
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", UnknownArguments.REJECT)
            response = _view(ServiceUpdateView, _update_spec(filter_set=_ByName))(
                request, pk=str(author.pk)
            )
        assert response.status_code == 200, response.data
