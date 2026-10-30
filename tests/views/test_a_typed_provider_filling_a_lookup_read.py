"""A ``kwargs`` provider and the name a target lookup reads.

The spec's ``kwargs`` provider's values reach the service once the target is
resolved, so a key its return annotation fills never reaches the lookup. The
kernel refuses such a spec when it is built, rather than demand that key of the
caller; drfs refused it at dispatch and at registration, so a kernel spec is
refused before a view or a route ever holds it. The lookup's own ``kwargs``
provider is the one that fills its reads, and over HTTP its key picks the row.

The kernel route's answer today, which no plan decision names yet: drfs let an untyped spec-level provider's ``pk`` pick the
row. On the kernel route the spec's provider never reaches the lookup, typed
or not, so a lookup requiring ``pk`` that nothing of its own fills is refused at
``as_view()``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict

import pytest
from django.core.exceptions import ImproperlyConfigured
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

from django_spec_rest import ServiceUpdateView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Post
from tests.testapp.serializers import PostSerializer

_factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _TitleIn(serializers.Serializer):
    title = serializers.CharField()


class _FillsPk(TypedDict):
    pk: int


def _typed(pk: int) -> Callable[[], _FillsPk]:
    def provider() -> _FillsPk:
        return {"pk": pk}

    return provider


def _untyped(pk: int) -> Callable[[], Any]:
    def provider():  # unannotated on purpose: it names no keys
        return {"pk": pk}

    return provider


def _selector(*, pk: int) -> Any:
    return Post.objects.get(pk=pk)


def _rename(*, instance: Post, data: dict[str, Any]) -> Post:
    instance.title = data["title"]
    instance.save()
    return instance


def _spec(*, lookup: SelectorSpec, **fields: Any) -> ServiceSpec:
    return ServiceSpec(
        service=_rename,
        validator=SerializerValidator(_TitleIn),
        presenter=SerializerPresenter(PostSerializer),
        instance_selector_spec=lookup,
        permissions=_OPEN,
        atomic=False,
        **fields,
    )


class _UpdateView(ServiceUpdateView):
    permission_classes = []

    def get_permissions(self) -> list[Any]:
        # ``MutationFlowMixin``'s reads a drfs-only field; the spine's views
        # answer the view's own classes the same way.
        return [permission() for permission in self.permission_classes]


def test_a_typed_spec_level_provider_filling_the_lookup_s_read_is_refused_when_built() -> None:
    reads = Parameters((Parameter("pk", "integer", required=True),))

    with pytest.raises(
        ImproperlyConfigured,
        match=r"ServiceSpec\.kwargs is annotated to fill \['pk'\], which "
        r"ServiceSpec\.instance_selector_spec\.reads declares, and its values never reach "
        r"ServiceSpec\.instance_selector_spec\.reads",
    ):
        _spec(
            lookup=SelectorSpec(kind=SelectorKind.RETRIEVE, selector=_selector, reads=reads),
            kwargs=_typed(1),
        )


def test_an_untyped_spec_level_provider_never_fills_the_lookup() -> None:
    spec = _spec(
        lookup=SelectorSpec(kind=SelectorKind.RETRIEVE, selector=_selector), kwargs=_untyped(1)
    )

    with pytest.raises(
        ImproperlyConfigured,
        match=r"ServiceSpec\.instance_selector_spec\.selector requires the keyword\(s\) "
        r"\['pk'\], which nothing fills",
    ):
        type("_View", (_UpdateView,), {"spec": spec}).as_view()


@pytest.mark.django_db
def test_the_lookup_s_own_typed_provider_picks_the_row_over_http() -> None:
    post = Post.objects.create(title="old")
    other = Post.objects.create(title="other")
    spec = _spec(
        lookup=SelectorSpec(kind=SelectorKind.RETRIEVE, selector=_selector, kwargs=_typed(other.pk))
    )
    view = type("_View", (_UpdateView,), {"spec": spec}).as_view()

    response = view(_factory.patch("/", {"title": "new"}, format="json"), pk=post.pk)

    assert response.status_code == 200, response.data
    assert response.data["id"] == other.pk
    assert Post.objects.get(pk=other.pk).title == "new"
    assert Post.objects.get(pk=post.pk).title == "old"
