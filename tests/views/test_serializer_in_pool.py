"""The bound input serializer a ``SerializerValidator`` hands a kernel service, over HTTP.

A service declaring ``serializer`` is handed the serializer that validated the
body, bound to it and, on an update, to the row, so persistence may live on
the serializer (``serializer.save()``). A client cannot stand a value in for
it: a body key ``serializer`` no field declares is an argument the spec does
not declare, which the kernel's unknown-argument policy answers.
"""

from __future__ import annotations

from typing import Any

import pytest
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
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView, ServiceUpdateView
from django_spec_rest.dispatch import kernel_edge
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Post, Tag

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _PostWithTagsSerializer(serializers.ModelSerializer):
    """Nested-write serializer: persistence lives on the serializer."""

    tags = serializers.ListField(child=serializers.CharField(), required=False)

    class Meta:
        model = Post
        fields = ("id", "title", "tags")

    def create(self, validated_data: dict[str, Any]) -> Post:
        tag_names: list[str] = validated_data.pop("tags", [])
        post = Post.objects.create(**validated_data)
        for name in tag_names:
            post.tags.add(Tag.objects.create(name=name))
        return post

    def update(self, instance: Post, validated_data: dict[str, Any]) -> Post:
        tag_names: list[str] = validated_data.pop("tags", [])
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        for name in tag_names:
            instance.tags.add(Tag.objects.create(name=name))
        return instance


class _OwnPermissions:
    """``get_permissions`` answers the view's own classes, as for a spec setting none.

    ``MutationFlowMixin.get_permissions`` reads ``spec.permission_classes``,
    which a kernel spec has no attribute for.
    """

    permission_classes: Any

    def get_permissions(self) -> list[Any]:
        return [permission() for permission in self.permission_classes]


def _spec(service: Any, **extra: Any) -> ServiceSpec:
    return ServiceSpec(
        service=service,
        permissions=_OPEN,
        validator=SerializerValidator(_PostWithTagsSerializer),
        **extra,
    )


def _create(service: Any, body: dict[str, Any]) -> Any:
    view = type("_View", (_OwnPermissions, ServiceCreateView), {"spec": _spec(service)})
    return view.as_view()(factory.post("/", body, format="json"))


def test_a_create_s_service_is_handed_the_bound_validated_serializer() -> None:
    captured: dict[str, Any] = {}

    def service(*, serializer: Any) -> None:
        captured.update(serializer=serializer, instance_before_save=serializer.instance)
        serializer.save()

    assert _create(service, {"title": "hello"}).status_code == 204
    bound = captured["serializer"]
    assert isinstance(bound, _PostWithTagsSerializer)
    assert bound.validated_data == {"title": "hello"}
    assert captured["instance_before_save"] is None
    assert Post.objects.filter(title="hello").exists()


def test_a_nested_write_saves_through_the_serializer() -> None:
    def service(*, serializer: Any) -> None:
        serializer.save()

    response = _create(service, {"title": "tagged", "tags": ["a", "b"]})
    assert response.status_code == 204
    post = Post.objects.get(title="tagged")
    assert sorted(post.tags.values_list("name", flat=True)) == ["a", "b"]


def test_an_update_s_serializer_is_bound_to_the_row_and_saves_it() -> None:
    captured: dict[str, Any] = {}

    def service(*, serializer: Any) -> None:
        captured["instance"] = serializer.instance
        serializer.save()

    spec = _spec(
        service,
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, pk: Post.objects.filter(pk=pk).first(),
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
            permissions=_OPEN,
        ),
    )
    view = type("_View", (_OwnPermissions, ServiceUpdateView), {"spec": spec})
    post = Post.objects.create(title="orig")

    response = view.as_view()(factory.put("/", {"title": "renamed"}, format="json"), pk=post.pk)

    assert response.status_code == 204
    assert captured["instance"] == post
    post.refresh_from_db()
    assert post.title == "renamed"
    # ``serializer.save()`` took the update path: no second row.
    assert Post.objects.count() == 1


def test_a_service_not_declaring_the_serializer_is_unaffected() -> None:
    def service(*, data: dict[str, Any]) -> None:
        Post.objects.create(title=data["title"])

    assert _create(service, {"title": "plain"}).status_code == 204
    assert Post.objects.filter(title="plain").exists()


@pytest.mark.parametrize("policy", [UnknownArguments.REJECT, UnknownArguments.IGNORE])
def test_a_body_key_named_serializer_never_stands_in_for_it(
    policy: UnknownArguments, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refused as an unknown argument under ``REJECT``; dropped unseen under
    ``IGNORE``, the service still handed the bound serializer. On the drfs path
    the edge stripped the key and the call went on, which ``IGNORE`` keeps."""
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", policy)
    captured: dict[str, Any] = {}

    def service(*, serializer: Any) -> None:
        captured["serializer"] = serializer
        serializer.save()

    response = _create(service, {"title": "x", "serializer": "evil"})

    if policy is UnknownArguments.REJECT:
        assert response.status_code == 400
        # The whole body: the unknown key under its wire name, nothing else refused.
        assert response.data == {"serializer": ["Unknown argument."]}
        assert captured == {}
    else:
        assert response.status_code == 204
        assert isinstance(captured["serializer"], _PostWithTagsSerializer)
