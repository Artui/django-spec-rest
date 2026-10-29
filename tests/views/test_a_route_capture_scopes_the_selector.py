"""A route capture scopes a kernel selector, and what the spec's own provider says of it.

Ported from the offline route-capture rows of the drfs dispatch suite, onto
the live view: the capture is the scope and a client's query value cannot
move it (``test_url_kwarg_over_http``), while the spec's own ``kwargs``
provider is the server's word and outranks the route, as drfs answered.
"""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import Parameter, Parameters, SelectorKind, SelectorSpec, Unrestricted
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorListView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Author, Post

pytestmark = pytest.mark.django_db


class _PostOut(serializers.Serializer):
    title = serializers.CharField()


def _posts_of(*, author_pk: int) -> Any:
    return Post.objects.filter(author_id=author_pk).order_by("id")


def test_the_spec_s_provider_outranks_the_route() -> None:
    a1, a2 = Author.objects.create(name="a1"), Author.objects.create(name="a2")
    Post.objects.create(title="a1-post", author=a1)
    Post.objects.create(title="a2-post", author=a2)

    def scope() -> dict[str, Any]:
        return {"author_pk": a2.pk}

    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=_posts_of,
        reads=Parameters.of(Parameter("author_pk", "integer")),
        kwargs=scope,
        permissions=(Unrestricted(),),
        presenter=SerializerPresenter(_PostOut),
    )
    view = type("_View", (SelectorListView,), {"spec": spec})
    response = view.as_view()(APIRequestFactory().get("/"), author_pk=str(a1.pk))
    assert response.status_code == 200
    assert response.data == [{"title": "a2-post"}]
