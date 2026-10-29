"""A kernel spec's ``affordances`` over HTTP: the status, the body, and what a denied caller learns.

Read off the rendered response, because the wire is what a client sees. The
update view's row is found by the spec's own ``instance_selector_spec``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q
from django_service_specs import (
    Affordance,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView, ServiceUpdateView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Post
from tests.testapp.serializers import PostSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)

UNPUBLISHED = Affordance(
    code="already_published",
    reason="This post is already published and cannot be published again.",
    when=Q(published=False),
)


class _NotThisPost(Unrestricted):
    message = "You may not touch this post."

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        return False


def _publish(*, instance: Post) -> Post:
    instance.published = True
    instance.save(update_fields=["published"])
    return instance


def _view(permissions: Any = _OPEN) -> Any:
    spec = ServiceSpec(
        service=_publish,
        permissions=permissions,
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, pk: Post.objects.filter(pk=pk).first(),
            reads=Parameters.of(Parameter("pk", "integer")),
            permissions=_OPEN,
        ),
        presenter=SerializerPresenter(PostSerializer),
        affordances=[UNPUBLISHED],
    )

    class _Publish(ServiceUpdateView):
        """``get_permissions`` stands in for ``MutationFlowMixin``'s, which
        reads a drfs spec's ``permission_classes``, as the spine's views do."""

        def get_permissions(self) -> list[Any]:
            return [permission() for permission in self.permission_classes]

    return type("_View", (_Publish,), {"spec": spec}).as_view()


def _patch(view: Any, pk: int) -> Any:
    response = view(factory.patch("/", {}, format="json"), pk=str(pk))
    response.render()
    return response


def test_an_unavailable_row_is_a_409_carrying_the_code_beside_the_detail() -> None:
    post = Post.objects.create(title="t", published=True)
    response = _patch(_view(), post.pk)
    assert response.status_code == 409
    assert json.loads(response.content) == {
        "detail": "This post is already published and cannot be published again.",
        "code": "already_published",
    }


def test_an_available_row_is_served() -> None:
    post = Post.objects.create(title="t", published=False)
    response = _patch(_view(), post.pk)
    assert response.status_code == 200
    assert json.loads(response.content)["published"] is True


def test_a_caller_denied_the_row_learns_nothing_about_its_state() -> None:
    """The object-level refusal comes before the affordance, so a caller
    refused the row is answered 403, never told it is already published."""
    post = Post.objects.create(title="t", published=True)
    response = _patch(_view(permissions=(_NotThisPost(),)), post.pk)
    assert response.status_code == 403
    assert "already_published" not in response.content.decode()


@pytest.mark.xfail(
    strict=True,
    reason="validate_mutation_view_spec does not refuse a kernel spec's row condition with no "
    "row at as_view(); the kernel refuses it only at dispatch. An ask on views/spec_validation.py",
)
def test_a_row_condition_on_a_create_view_is_refused_at_as_view() -> None:
    """A create resolves no row, so a condition on one cannot be answered."""
    spec = ServiceSpec(service=lambda: None, permissions=_OPEN, affordances=[UNPUBLISHED])
    with pytest.raises(ImproperlyConfigured):
        type("_View", (ServiceCreateView,), {"spec": spec}).as_view()
