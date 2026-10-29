"""A list view reads its query string by the kernel's rules, through ``flat_arguments``.

The rows of the client-visible differences the flat reader decision records:
a ``FilterSet`` over ``User`` beside a declared ``limit`` read, three users,
each query string asserting the status, the rows served and, for a
refusal, its wire shape. Against drfs these differ on purpose:

- **a blank value is absent** where the parameter cannot take ``""``, so
  ``?id=``, ``?staff=``, ``?joined=``, ``?kind=``, ``?st=`` and ``?limit=``
  answer every row, as django-filter itself answers them, where drfs from
  0.58 answered each 400;
- **a comma splits a typed array**, so ``?st=ann,bob`` is two choices, where
  drfs refused it;
- **drfs' CSV post-pass drops**, so ``?ids=1,,3`` is refused at its empty
  element rather than read as ``[1, 3]``.
"""

from __future__ import annotations

import json
from typing import Any

import django_filters
import pytest
from django.contrib.auth.models import User
from django_service_specs import Parameter, Parameters, SelectorKind, SelectorSpec, Unrestricted
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorListView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter

pytestmark = pytest.mark.django_db

_CHOICES = [("ann", "ann"), ("bob", "bob"), ("cy", "cy")]


class _NumberIn(django_filters.BaseInFilter, django_filters.NumberFilter):
    pass


class _Users(django_filters.FilterSet):
    id = django_filters.NumberFilter()
    ids = _NumberIn(field_name="id", lookup_expr="in")
    staff = django_filters.BooleanFilter(field_name="is_staff")
    joined = django_filters.DateFilter(field_name="date_joined", lookup_expr="date")
    name = django_filters.CharFilter(field_name="username")
    kind = django_filters.ChoiceFilter(field_name="username", choices=_CHOICES[:2])
    o = django_filters.OrderingFilter(fields=("username", "id"))
    st = django_filters.MultipleChoiceFilter(field_name="username", choices=_CHOICES)

    class Meta:
        model = User
        fields: list[str] = []


class _Out(serializers.Serializer):
    username = serializers.CharField()


def _users(*, limit: int | None = None) -> Any:
    rows = User.objects.order_by("id")
    return rows[:limit] if limit is not None else rows


class _View(SelectorListView):
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=_users,
        reads=Parameters.of(Parameter("limit", "integer", required=False)),
        filter_set=_Users,
        permissions=(Unrestricted(),),
        presenter=SerializerPresenter(_Out),
    )


@pytest.fixture
def pks() -> list[int]:
    ann = User.objects.create(username="ann")
    bob = User.objects.create(username="bob", is_staff=True)
    cy = User.objects.create(username="cy")
    return [ann.pk, bob.pk, cy.pk]


def _answer(query: str) -> tuple[int, Any]:
    response = _View.as_view()(APIRequestFactory().get("/?" + query))
    if response.status_code == 200:
        return 200, [row["username"] for row in response.data]
    return response.status_code, response.data


_ALL = ["ann", "bob", "cy"]


@pytest.mark.parametrize(
    ("query", "rows"),
    [
        # A blank is absent: every row, as django-filter answers it.
        ("id=", _ALL),
        ("staff=", _ALL),
        ("joined=", _ALL),
        ("kind=", _ALL),
        ("st=", _ALL),
        ("limit=", _ALL),
        # A comma splits a string array whose choices hold none.
        ("st=ann,bob", ["ann", "bob"]),
        ("st=ann&st=bob", ["ann", "bob"]),
        # Agreeing with drfs and django-filter.
        ("", _ALL),
        ("staff=true", ["bob"]),
        ("name=", _ALL),
        ("o=-id", ["cy", "bob", "ann"]),
        ("o=username,-id", _ALL),
        ("o=", _ALL),
        ("limit=2", ["ann", "bob"]),
        ("ids=", _ALL),
    ],
)
def test_a_query_string_answers_its_rows(pks: list[int], query: str, rows: list[str]) -> None:
    assert _answer(query) == (200, rows)


@pytest.mark.parametrize(
    ("query", "rows"),
    [
        ("id={1}", ["bob"]),
        ("id={0}&id={1}", ["bob"]),
        ("ids={0},{2}", ["ann", "cy"]),
        ("ids={0},%20{2}", ["ann", "cy"]),
        ("ids={0}&ids={2}", ["ann", "cy"]),
    ],
)
def test_a_number_filter_reads_its_values(pks: list[int], query: str, rows: list[str]) -> None:
    """``?id=1&id=2`` is its last value, as ``QueryDict`` reads a repeated key."""
    assert _answer(query.format(*pks)) == (200, rows)


def test_an_empty_csv_element_is_refused_at_its_index(pks: list[int]) -> None:
    """drfs' post-pass read ``?ids=1,,3`` as ``[1, 3]``; the kernel refuses
    the empty part, keyed by the filter's name and then the element's index,
    where drfs refused a bad element as a flat list under the filter's name.
    Read off the rendered body, the payload a client is served."""
    response = _View.as_view()(APIRequestFactory().get(f"/?ids={pks[0]},,{pks[2]}"))
    response.render()
    assert response.status_code == 400
    assert json.loads(response.content) == {"ids": {"1": ["Enter a number."]}}


def test_an_array_past_its_cap_is_refused(pks: list[int]) -> None:
    status, body = _answer("ids=" + ",".join(["1"] * 1001))
    assert status == 400
    assert "no more than 1000 elements" in str(body["ids"])


def test_an_uncoercible_read_is_refused(pks: list[int]) -> None:
    status, body = _answer("limit=x")
    assert status == 400
    assert list(body) == ["limit"]


def _served(query: str) -> tuple[int, Any]:
    response = _View.as_view()(APIRequestFactory().get("/?" + query))
    response.render()
    return response.status_code, json.loads(response.content)


@pytest.mark.parametrize(
    ("query", "name", "value"), [("o=bogus", "o", "bogus"), ("st=dan", "st", "dan")]
)
def test_a_refused_choice_is_keyed_at_its_index(
    pks: list[int], query: str, name: str, value: str
) -> None:
    """The answer served today, and a change the flat reader decision does
    not list: an ordering or multiple-choice filter is an array to the
    kernel, so a refused value is keyed by its index under the filter's name,
    where drfs served a flat list under the name
    (``{"ordering": ["Select a valid choice. ..."]}``)."""
    message = f"Select a valid choice. {value} is not one of the available choices."
    assert _served(query) == (400, {name: {"0": [message]}})
