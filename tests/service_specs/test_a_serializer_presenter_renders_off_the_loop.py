"""The kernel's ``apresent`` over a ``SerializerPresenter``: the render step, off the event loop.

A lazy queryset's first iteration and the serializer context callable's query
are ORM work, which Django refuses on the loop. Each list case here runs under ``adispatch`` and ``apresent`` from a
coroutine, so each fails with ``SynchronousOnlyOperation`` if ``present`` ran
on the loop instead; a single row ``adispatch`` already fetched renders either
way, and holds only that the result is the same. With no request carried, the
serializer still finds one, an offline request whose ``user`` is the call's
principal.
The passthrough cases, a spec with no presenter, are the kernel's own.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser, User
from django.db.models import QuerySet
from django_service_specs import SelectorKind, SelectorSpec, Unrestricted
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.apresent import apresent
from rest_framework import serializers

from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Post

pytestmark = pytest.mark.django_db(transaction=True)

_OPEN = (Unrestricted(),)


class _PostSerializer(serializers.ModelSerializer):
    class Meta:
        model = Post
        fields = ("id", "title")


def _all_posts() -> QuerySet[Post]:
    return Post.objects.all().order_by("id")


def _list(serializer: type, **presenter: Any) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=_all_posts,
        permissions=_OPEN,
        presenter=SerializerPresenter(serializer, **presenter),
    )


async def _rendered(spec: SelectorSpec, principal: Any = None) -> Any:
    result = await adispatch(spec, principal=principal or AnonymousUser(), arguments={})
    return await apresent(spec, result)


async def test_renders_the_lazy_queryset_adispatch_returns() -> None:
    await Post.objects.acreate(title="a")
    await Post.objects.acreate(title="b")

    rendered = await _rendered(_list(_PostSerializer))

    assert [row["title"] for row in rendered] == ["a", "b"]


async def test_renders_a_single_instance() -> None:
    post = await Post.objects.acreate(title="a")
    spec = SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda: Post.objects.filter(pk=post.pk),
        permissions=_OPEN,
        presenter=SerializerPresenter(_PostSerializer),
    )

    assert await _rendered(spec) == {"id": post.pk, "title": "a"}


async def test_the_serializer_context_callable_may_query() -> None:
    await Post.objects.acreate(title="a")

    class _CountingSerializer(serializers.ModelSerializer):
        total = serializers.SerializerMethodField()

        class Meta:
            model = Post
            fields = ("id", "total")

        def get_total(self, _: Post) -> int:
            return self.context["total"]

    def context(*, result: Post) -> dict[str, Any]:
        # Asked once per row, with the row under ``value_keyword``.
        return {"total": Post.objects.filter(pk=result.pk).count()}

    rendered = await _rendered(_list(_CountingSerializer, serializer_context=context))

    assert [row["total"] for row in rendered] == [1]


async def test_the_baseline_context_reaches_the_serializer() -> None:
    await Post.objects.acreate(title="a")
    alice = await User.objects.acreate(username="alice")

    class _RequestReadingSerializer(serializers.ModelSerializer):
        who = serializers.SerializerMethodField()

        class Meta:
            model = Post
            fields = ("id", "who")

        def get_who(self, _: Post) -> str:
            return self.context["request"].user.username

    rendered = await _rendered(_list(_RequestReadingSerializer), principal=alice)

    assert [row["who"] for row in rendered] == ["alice"]
