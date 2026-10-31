"""A kernel lookup's filter named like a field the body writes is refused.

The kernel has one argument namespace, so a lookup's ``filter_set`` filter and
a ``SerializerValidator`` field of one name would be one argument read two
ways. The kernel refuses the spec as declaring it twice when its parameters
are first read, which is the first request; ``as_view()`` does not refuse it
for a kernel spec yet. A name the body does not
write is accepted.
"""

from __future__ import annotations

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

from django_spec_rest import ServiceUpdateView
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author

_OPEN = (Unrestricted(),)


class _AuthorIn(serializers.Serializer):
    name = serializers.CharField()


class _ByName(django_filters.FilterSet):
    name = django_filters.CharFilter()

    class Meta:
        model = Author
        fields: list[str] = []


class _ByScope(django_filters.FilterSet):
    scope = django_filters.CharFilter(field_name="name")

    class Meta:
        model = Author
        fields: list[str] = []


def _author_by_pk(*, pk: int) -> QuerySet[Author]:
    return Author.objects.filter(pk=pk)


def _spec(filter_set: type) -> ServiceSpec:
    return ServiceSpec(
        service=lambda *, instance, data: instance,
        permissions=_OPEN,
        validator=SerializerValidator(_AuthorIn),
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=_author_by_pk,
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
            filter_set=filter_set,
        ),
    )


def test_an_instance_lookup_s_filter_named_like_a_field_is_refused() -> None:
    with pytest.raises(ImproperlyConfigured, match=r"\['name'\] are declared by two sources"):
        _spec(_ByName).parameters()


def test_it_is_refused_at_as_view() -> None:
    view = type("_View", (ServiceUpdateView,), {"spec": _spec(_ByName)})
    with pytest.raises(ImproperlyConfigured, match="declared by two sources"):
        view.as_view()


def test_a_name_the_body_does_not_write_is_accepted() -> None:
    assert "scope" in _spec(_ByScope).parameters().names()
