"""A kernel selector spec's ``filter_set`` runs off the event loop under the async edge.

A filter method that evaluates a queryset is sync ORM work, and
``adispatch_kernel_spec`` must run it in the kernel's executor hop rather than
on the loop, where Django refuses it with ``SynchronousOnlyOperation``. The
sync edge runs the same spec as a control.
"""

from __future__ import annotations

from typing import Any

import django_filters
import pytest
from asgiref.sync import sync_to_async
from django.db.models import QuerySet
from django_service_specs import SelectorKind, SelectorSpec, Unrestricted
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorListView
from django_spec_rest.dispatch.kernel_edge import adispatch_kernel_spec, dispatch_kernel_spec
from django_spec_rest.views.utils import view_call_context
from tests.testapp.models import Post


class _EvaluatingFilterSet(django_filters.FilterSet):
    """A ``filter_set`` whose filter method needs rows to decide: it evaluates."""

    seen = django_filters.NumberFilter(method="filter_seen")

    def filter_seen(self, queryset: Any, name: str, value: Any) -> Any:
        return queryset.filter(pk__in=[post.pk for post in Post.objects.all()])

    class Meta:
        model = Post
        fields: list[str] = []


def _all_posts() -> QuerySet[Post]:
    return Post.objects.all()


_SPEC = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=_all_posts,
    filter_set=_EvaluatingFilterSet,
    permissions=(Unrestricted(),),
)


def _view() -> Any:
    view = type("_View", (SelectorListView,), {"spec": _SPEC})()
    view.setup(APIRequestFactory().get("/?seen=1"))
    view.request = view.initialize_request(view.request)
    view.format_kwarg = None
    return view


@pytest.mark.django_db(transaction=True)
async def test_a_filter_set_that_queries_runs_off_the_loop() -> None:
    await Post.objects.acreate(title="a")
    view = await sync_to_async(_view)()
    result = await adispatch_kernel_spec(
        _SPEC,
        view=view,
        request=view.request,
        call_context=view_call_context(view, view.request),
    )
    assert await result.value.acount() == 1


@pytest.mark.django_db
def test_the_sync_edge_runs_it_too() -> None:
    Post.objects.create(title="a")
    view = _view()
    result = dispatch_kernel_spec(
        _SPEC, view=view, request=view.request, call_context=view_call_context(view, view.request)
    )
    assert result.value.count() == 1
