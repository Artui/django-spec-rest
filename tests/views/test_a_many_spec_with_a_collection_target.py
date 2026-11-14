from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import SelectorKind, SelectorSpec, ServiceSpec, Unrestricted
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceUpdateView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Post

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
seen: dict[str, Any] = {}


class _Row(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()


class _Out(serializers.ModelSerializer):
    class Meta:
        model = Post
        fields = ("id", "title")


class _Recording(SerializerValidator):
    def validated_many(self, rows: Any, context: Any, *, many_argument: str) -> Any:
        result = super().validated_many(rows, context, many_argument=many_argument)
        seen["target"] = context.target
        seen["instance"] = result.pool["serializer"].instance
        seen["list"] = isinstance(result.pool["serializer"], serializers.ListSerializer)
        return result


def _rename(*, data: list[dict[str, Any]]) -> list[Post]:
    for row in data:
        Post.objects.filter(pk=row["id"]).update(title=row["title"])
    return list(Post.objects.order_by("id"))


def _spec() -> ServiceSpec:
    return ServiceSpec(
        service=_rename,
        permissions=(Unrestricted(),),
        validator=_Recording(_Row),
        presenter=SerializerPresenter(_Out),
        many=True,
        collection_selector_spec=SelectorSpec(
            kind=SelectorKind.LIST, selector=lambda: Post.objects.order_by("id")
        ),
        atomic=False,
    )


def _put(body: Any) -> Any:
    view = type("_View", (ServiceUpdateView,), {"spec": _spec()}).as_view()
    return view(factory.put("/", body, format="json"))


def test_the_rows_dispatch_validated_as_a_list_serializer_with_no_instance() -> None:
    seen.clear()
    a, b = Post.objects.create(title="a"), Post.objects.create(title="b")
    response = _put([{"id": a.pk, "title": "x"}, {"id": b.pk, "title": "y"}])
    assert response.status_code == 200
    assert [row["title"] for row in response.data] == ["x", "y"]
    assert seen["list"] is True
    assert seen["target"].model is Post
    assert seen["instance"] is None


def test_a_bad_row_is_refused_by_index() -> None:
    a = Post.objects.create(title="a")
    response = _put([{"id": a.pk, "title": "x"}, {"id": a.pk}])
    assert response.status_code == 400
    assert Post.objects.get().title == "a"
