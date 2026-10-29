"""``drf_query_keys`` and ``kernel_query``: DRF's own query keys, kept off a kernel spec's arguments.

The hand-off into the dispatch is not built yet (``test_selector_list_view``'s
``TestDRFsOwnQueryKeys`` holds it as a strict xfail), so the two are held here
on their own.
"""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import Parameter, Parameters, SelectorKind, SelectorSpec, Unrestricted
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import CursorPagination, LimitOffsetPagination, PageNumberPagination
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, override_settings
from rest_framework.versioning import QueryParameterVersioning

from django_spec_rest.selectors.utils import drf_query_keys, kernel_query


class _View:
    def __init__(
        self,
        paginator: Any = None,
        filter_backends: tuple[Any, ...] = (),
        versioning_class: Any = None,
    ) -> None:
        self.paginator = paginator
        self.filter_backends = filter_backends
        self.versioning_class = versioning_class


class _SizedPages(PageNumberPagination):
    page_size_query_param = "size"


class _OwnFilter:
    """A project's backend, spelling its key DRF's way."""

    tenant_param = "tenant"
    blank_param = ""
    unrelated = "not a key"


@pytest.mark.parametrize(
    ("view", "keys"),
    [
        (_View(), {"format"}),
        (_View(PageNumberPagination()), {"format", "page"}),
        (_View(_SizedPages()), {"format", "page", "size"}),
        (_View(LimitOffsetPagination()), {"format", "limit", "offset"}),
        (_View(CursorPagination()), {"format", "cursor"}),
        (_View(filter_backends=(OrderingFilter, SearchFilter)), {"format", "ordering", "search"}),
        (_View(filter_backends=(_OwnFilter,)), {"format", "tenant"}),
        (_View(versioning_class=QueryParameterVersioning), {"format", "version"}),
    ],
)
def test_drf_query_keys(view: _View, keys: set[str]) -> None:
    """A ``None`` key, ``PageNumberPagination``'s unset ``page_size_query_param``,
    names none, and an attribute not spelled ``*_param`` is no key."""
    assert drf_query_keys(view) == keys


@override_settings(REST_FRAMEWORK={"URL_FORMAT_OVERRIDE": None})
def test_no_format_override_names_no_format_key() -> None:
    assert drf_query_keys(_View()) == frozenset()


def _spec(*reads: Parameter) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda **_: [],
        reads=Parameters.of(*reads),
        permissions=(Unrestricted(),),
    )


def _request(query: str) -> Request:
    return Request(APIRequestFactory().get("/?" + query))


def test_kernel_query_drops_drf_s_keys_and_keeps_the_rest() -> None:
    request = _request("page=2&format=json&ordering=-id&q=x&q=y")
    view = _View(PageNumberPagination(), (OrderingFilter,))
    query = kernel_query(view, _spec(), request)
    assert dict(query.lists()) == {"q": ["x", "y"]}
    # A copy: the paginator and the backends still read the request's own.
    assert request.query_params["page"] == "2"


def test_a_read_named_like_a_drf_key_is_still_the_spec_s() -> None:
    query = kernel_query(
        _View(PageNumberPagination()),
        _spec(Parameter("page", "integer", required=True)),
        _request("page=2&format=json"),
    )
    assert dict(query.lists()) == {"page": ["2"]}
