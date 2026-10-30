"""A kernel selector's request-scoped ``FilterSet`` is handed the request the call carries.

As ``DjangoFilterBackend`` hands it, a ``FilterSet`` declaring ``request`` finds
the call's: the offline pair's, for a caller outside HTTP (the bridges to other
transports build one), and the DRF request itself on a live view. The kernel
hands it by the declare-to-receive rule from the call's context.
"""

from __future__ import annotations

from typing import Any

import django_filters
import pytest
from django.contrib.auth.models import AnonymousUser
from django_service_specs import SelectorKind, SelectorSpec, Unrestricted
from django_service_specs.dispatch.dispatch import dispatch
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorListView
from django_spec_rest.service_specs.build_offline_context import build_offline_context
from tests.testapp.models import Post
from tests.testapp.serializers import PostSerializer

pytestmark = pytest.mark.django_db

captured: dict[str, Any] = {}


class _RequestAwareFilterSet(django_filters.FilterSet):
    published = django_filters.BooleanFilter()

    class Meta:
        model = Post
        fields = ["published"]

    def __init__(self, *args: Any, request: Any = None, **kwargs: Any) -> None:
        captured["request"] = request
        super().__init__(*args, request=request, **kwargs)


def _spec() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda: Post.objects.all(),
        permissions=(Unrestricted(),),
        filter_set=_RequestAwareFilterSet,
    )


@pytest.fixture(autouse=True)
def _clear() -> None:
    captured.clear()


def test_the_offline_request_reaches_the_filter_set_with_the_acting_user() -> None:
    context = build_offline_context("ada", {})

    dispatch(
        _spec(),
        principal=AnonymousUser(),
        arguments={},
        call_context={"request": context.request, "view": context.view},
    )

    assert captured["request"] is context.request
    assert captured["request"].user == "ada"


def test_a_live_view_hands_the_filter_set_its_own_request() -> None:
    view = type(
        "_View", (SelectorListView,), {"spec": _spec(), "serializer_class": PostSerializer}
    ).as_view()

    response = view(APIRequestFactory().get("/"))

    assert response.status_code == 200, getattr(response, "data", None)
    assert isinstance(captured["request"], Request)
