"""``SelectorRetrieveView`` over a kernel ``SelectorSpec``.

The spec's own ``presenter`` renders the row, with the affordance answers it
declares; ``None`` under ``allow_none`` is a ``200`` with a JSON ``null`` body;
the view's object permission is asked inside the dispatch, before the spec's
preconditions and before anything is presented.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q, QuerySet
from django_service_specs import (
    Affordance,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.authentication import BasicAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest import SelectorRetrieveView
from django_spec_rest.selectors.utils import _viewed
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Author, Post
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_PK = Parameters.of(Parameter("pk", "integer", required=True))


class _NameOnly(serializers.Serializer):
    name = serializers.CharField()


def _first(*, pk: int) -> Author | None:
    return Author.objects.filter(pk=pk).first()


def _detail(selector: Any = _first, **fields: Any) -> SelectorSpec:
    fields.setdefault("permissions", _OPEN)
    return SelectorSpec(kind=SelectorKind.RETRIEVE, selector=selector, reads=_PK, **fields)


def _get(
    spec: SelectorSpec, pk: Any, attrs: dict[str, Any] | None = None, user: Any = None
) -> Response:
    view = type("_View", (SelectorRetrieveView,), {"spec": spec, **(attrs or {})})
    request = factory.get("/")
    if user is not None:
        force_authenticate(request, user=user)
    response = view.as_view()(request, pk=str(pk))
    response.render()
    return response


@pytest.fixture
def ada() -> Author:
    return Author.objects.create(name="Ada")


class TestThePresenter:
    def test_the_spec_s_presenter_renders_the_row(self, ada: Author) -> None:
        """The presenter's serializer, not the view's ``serializer_class``."""
        spec = _detail(presenter=SerializerPresenter(_NameOnly))
        response = _get(spec, ada.pk, attrs={"serializer_class": AuthorSerializer})
        assert json.loads(response.content) == {"name": "Ada"}

    def test_a_spec_with_no_presenter_is_rendered_by_serializer_class(self, ada: Author) -> None:
        response = _get(_detail(), ada.pk, attrs={"serializer_class": AuthorSerializer})
        assert json.loads(response.content) == {"id": ada.pk, "name": "Ada"}

    def test_a_none_is_404(self) -> None:
        assert _get(_detail(presenter=SerializerPresenter(_NameOnly)), 999).status_code == 404

    def test_a_does_not_exist_is_404(self) -> None:
        spec = _detail(
            lambda *, pk: Author.objects.get(pk=pk), presenter=SerializerPresenter(_NameOnly)
        )
        assert _get(spec, 999).status_code == 404


class TestAllowNone:
    def test_a_miss_is_a_200_with_a_json_null_body(self) -> None:
        presented: list[Any] = []

        class _Recording(SerializerPresenter):
            def presented(self, value: Any, context: Any) -> Any:
                presented.append(value)
                return super().presented(value, context)

        spec = _detail(presenter=_Recording(_NameOnly), allow_none=True)
        response = _get(spec, 999)
        assert response.status_code == 200
        assert response.content == b"null"
        assert response["Content-Type"] == "application/json"
        # ``None`` is not a row, so nothing presents it.
        assert presented == []

    def test_a_does_not_exist_under_allow_none_is_null_too(self) -> None:
        """The kernel's rule: a RETRIEVE's missing row is ``None`` or a
        ``DoesNotExist`` alike, so ``allow_none`` lets either through."""
        spec = _detail(
            lambda *, pk: Author.objects.get(pk=pk),
            presenter=SerializerPresenter(_NameOnly),
            allow_none=True,
        )
        response = _get(spec, 999)
        assert (response.status_code, response.content) == (200, b"null")

    def test_a_found_row_is_presented(self, ada: Author) -> None:
        spec = _detail(presenter=SerializerPresenter(_NameOnly), allow_none=True)
        assert json.loads(_get(spec, ada.pk).content) == {"name": "Ada"}

    def test_a_miss_with_no_presenter_is_null_too(self) -> None:
        spec = _detail(allow_none=True)
        response = _get(spec, 999, attrs={"serializer_class": AuthorSerializer})
        assert response.content == b"null"


class _NotAda(BasePermission):
    def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
        return obj.name != "Ada"


class TestTheViewsObjectPermission:
    def test_the_view_s_object_permission_is_asked_before_the_preconditions(
        self, ada: Author
    ) -> None:
        """A principal refused the row is never told what a rule over it says:
        the precondition would answer 400 had it run."""
        ran: list[Any] = []

        def never_on_a_refused_row(*, instance: Author) -> None:
            ran.append(instance)
            raise ValueError("A rule over the row.")

        spec = _detail(
            presenter=SerializerPresenter(_NameOnly), preconditions=[never_on_a_refused_row]
        )
        response = _get(spec, ada.pk, attrs={"permission_classes": [_NotAda]})
        assert response.status_code == 403
        assert ran == []

    def test_a_row_the_view_allows_is_presented(self) -> None:
        bo = Author.objects.create(name="Bo")
        spec = _detail(presenter=SerializerPresenter(_NameOnly))
        response = _get(spec, bo.pk, attrs={"permission_classes": [_NotAda]})
        assert json.loads(response.content) == {"name": "Bo"}

    def test_an_anonymous_caller_refused_the_row_is_asked_to_authenticate(
        self, ada: Author
    ) -> None:
        """DRF's own refusal leaves as it is: an unauthenticated caller with an
        authenticator offering a challenge is answered 401, not 403."""
        spec = _detail(presenter=SerializerPresenter(_NameOnly))
        attrs = {"permission_classes": [_NotAda], "authentication_classes": [BasicAuthentication]}
        response = _get(spec, ada.pk, attrs=attrs)
        assert response.status_code == 401
        assert "WWW-Authenticate" in response

    def test_a_spec_declaring_no_permissions_is_still_refused(self, ada: Author) -> None:
        """The view's check is added only beside the spec's own, so a spec
        declaring none is still the kernel's configuration error."""
        spec = _detail(presenter=SerializerPresenter(_NameOnly), permissions=None)
        with pytest.raises(ImproperlyConfigured, match="permissions"):
            _get(spec, ada.pk, attrs={"permission_classes": [_NotAda]})

    def test_the_twin_is_built_once_per_spec(self, ada: Author) -> None:
        spec = _detail(presenter=SerializerPresenter(_NameOnly))
        assert _viewed(spec) is _viewed(spec)
        assert _viewed(spec) is not spec
        assert _viewed(spec).permissions[1:] == spec.permissions

    def test_the_view_s_check_asked_with_no_call_context_refuses(self) -> None:
        check = _viewed(_detail()).permissions[0]
        assert check.has_permission(None, None) is True
        assert check.has_object_permission(None, None, object()) is False

    def test_a_spec_s_own_check_still_refuses(self, ada: Author) -> None:
        user = User.objects.create(username="u")

        class _Nobody(Unrestricted):
            def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
                return False

        spec = _detail(presenter=SerializerPresenter(_NameOnly), permissions=(_Nobody(),))
        assert _get(spec, ada.pk, user=user).status_code == 403


UNPUBLISHED = Affordance(
    code="already_published", reason="This post is already published.", when=Q(published=False)
)
PUBLISH = ServiceSpec(service=lambda: None, permissions=_OPEN, affordances=[UNPUBLISHED])


class _PostOut(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()


def _post(*, pk: int) -> QuerySet[Post]:
    return Post.objects.filter(pk=pk)


class TestAffordances:
    def test_the_row_carries_its_answers(self) -> None:
        post = Post.objects.create(title="out", published=True)
        spec = _detail(
            _post, presenter=SerializerPresenter(_PostOut), affordances={"publish": PUBLISH}
        )
        assert json.loads(_get(spec, post.pk).content) == {
            "id": post.pk,
            "title": "out",
            "affordances": {
                "publish": {
                    "available": False,
                    "code": "already_published",
                    "reason": "This post is already published.",
                }
            },
        }

    def test_a_miss_is_still_a_404(self) -> None:
        spec = _detail(
            _post, presenter=SerializerPresenter(_PostOut), affordances={"publish": PUBLISH}
        )
        assert _get(spec, 999).status_code == 404

    def test_a_none_under_allow_none_carries_none(self) -> None:
        spec = _detail(
            lambda *, pk: None,
            presenter=SerializerPresenter(_PostOut),
            affordances={"publish": PUBLISH},
            allow_none=True,
        )
        assert _get(spec, 1).content == b"null"

    def test_affordances_with_no_presenter_are_refused_rather_than_dropped(self) -> None:
        post = Post.objects.create(title="draft")
        spec = _detail(_post, affordances={"publish": PUBLISH})
        with pytest.raises(ImproperlyConfigured, match="Declare a presenter"):
            _get(spec, post.pk, attrs={"serializer_class": _PostOut})
