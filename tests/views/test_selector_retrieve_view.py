"""``SelectorRetrieveView`` over a kernel ``SelectorSpec``.

The spec's own ``presenter`` renders the row, with the affordance answers it
declares; ``None`` under ``allow_none`` is a ``200`` with a JSON ``null`` body;
the view's object permission is asked inside the dispatch, before the spec's
preconditions and before anything is presented.
"""

from __future__ import annotations

import dataclasses
import gc
import json
import weakref
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
from rest_framework.renderers import BaseRenderer, BrowsableAPIRenderer, JSONRenderer
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest import SelectorRetrieveView
from django_spec_rest.selectors.utils import _VIEWED, _viewed
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

    def test_a_dead_spec_leaves_no_twin_behind(self) -> None:
        """The weakref callback drops the entry when its spec dies, so an
        ``id`` Python reuses is never found holding a dead spec's twin."""
        spec = _detail(presenter=SerializerPresenter(_NameOnly))
        key = id(spec)
        _viewed(spec)
        assert key in _VIEWED
        del spec
        gc.collect()
        assert key not in _VIEWED

    def test_a_stale_entry_under_a_live_spec_s_id_is_not_its_twin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An entry whose weak reference names another spec, as a reused ``id``
        would leave one, is rebuilt rather than served."""
        spec = _detail(presenter=SerializerPresenter(_NameOnly))
        other = _detail(presenter=SerializerPresenter(_NameOnly))
        stale = _viewed(other)
        monkeypatch.setitem(_VIEWED, id(spec), (weakref.ref(other), stale))
        twin = _viewed(spec)
        assert twin is not stale
        assert twin.permissions[1:] == spec.permissions

    def test_a_row_that_is_no_model_is_not_asked_of_the_view(self) -> None:
        @dataclasses.dataclass
        class _Row:
            name: str

        class _ReadsMeta(BasePermission):
            def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
                return obj._meta is not None

        spec = _detail(lambda *, pk: _Row(name="Ada"), presenter=SerializerPresenter(_NameOnly))
        response = _get(spec, 1, attrs={"permission_classes": [_ReadsMeta]})
        assert (response.status_code, json.loads(response.content)) == (200, {"name": "Ada"})

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


class TestTheViewsHooks:
    def test_get_selector_kwargs_beside_a_kernel_spec_is_refused_at_as_view(self) -> None:
        """As on a list view: the hook never reaches a kernel spec, whose
        keywords are its own providers', so it is refused when the view is
        built rather than left unasked."""
        spec = _detail(presenter=SerializerPresenter(_NameOnly))
        with pytest.raises(ImproperlyConfigured, match="_View overrides get_selector_kwargs"):
            _get(spec, 1, attrs={"get_selector_kwargs": lambda self: {"tenant": "acme"}})


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


class _VendorJSON(JSONRenderer):
    media_type = "application/vnd.example+json"


class _EnvelopeJSON(JSONRenderer):
    """A JSON renderer wrapping every payload, ``None`` included."""

    def render(
        self, data: Any, accepted_media_type: Any = None, renderer_context: Any = None
    ) -> bytes:
        return super().render({"data": data}, accepted_media_type, renderer_context)


class _CharsetJSON(JSONRenderer):
    charset = "utf-8"


class _SilentNone(BaseRenderer):
    """A non-JSON renderer that, like ``JSONRenderer``, renders ``None`` as nothing."""

    media_type = "text/plain"
    format = "txt"

    def render(
        self, data: Any, accepted_media_type: Any = None, renderer_context: Any = None
    ) -> bytes:
        return b"" if data is None else repr(data).encode()


class TestAMissOnTheWire:
    """What a client receives for ``allow_none``'s miss, read from the rendered bytes."""

    def _get(self, renderers: list[Any], pk: Any = 999, **headers: Any) -> Response:
        spec = _detail(presenter=SerializerPresenter(_NameOnly), allow_none=True)
        view = type("_View", (SelectorRetrieveView,), {"spec": spec, "renderer_classes": renderers})
        response = view.as_view()(factory.get("/", **headers), pk=str(pk))
        response.render()
        return response

    def test_an_indented_json_request_is_still_null(self) -> None:
        response = self._get([JSONRenderer], HTTP_ACCEPT="application/json; indent=4")
        assert (response.content, response["Content-Type"]) == (b"null", "application/json")

    def test_a_json_renderer_subclass_serves_null_under_its_own_media_type(self) -> None:
        response = self._get([_VendorJSON])
        assert response.content == b"null"
        assert response["Content-Type"] == "application/vnd.example+json"

    def test_a_json_renderer_that_wraps_none_keeps_its_wrapper(self, ada: Author) -> None:
        found, miss = self._get([_EnvelopeJSON], ada.pk), self._get([_EnvelopeJSON])
        assert found.content == b'{"data":{"name":"Ada"}}'
        assert miss.content == b'{"data":null}'
        assert miss["Content-Type"] == found["Content-Type"] == "application/json"

    def test_a_charset_renderer_serves_a_miss_under_the_header_of_a_found_row(
        self, ada: Author
    ) -> None:
        found, miss = self._get([_CharsetJSON], ada.pk), self._get([_CharsetJSON])
        assert found["Content-Type"] == "application/json; charset=utf-8"
        assert (miss.content, miss["Content-Type"]) == (b"null", found["Content-Type"])

    def test_a_non_json_renderer_that_renders_none_as_nothing_still_does(self) -> None:
        response = self._get([_SilentNone])
        assert response.content == b""
        assert "Content-Type" not in response

    def test_the_browsable_api_still_renders_a_miss(self, settings: Any) -> None:
        settings.TEMPLATES = [
            {"BACKEND": "django.template.backends.django.DjangoTemplates", "APP_DIRS": True}
        ]
        response = self._get([JSONRenderer, BrowsableAPIRenderer], HTTP_ACCEPT="text/html")
        assert response["Content-Type"] == "text/html; charset=utf-8"
        assert b"<html" in response.content


class TestGetObject:
    def test_with_a_spec_it_is_the_row_the_selector_finds(self, ada: Author) -> None:
        """A method of the view's own asking ``get_object()`` is handed the row
        the spec's selector finds, not one DRF's lookup would."""

        def post(self: Any, request: Any, *args: Any, **kwargs: Any) -> Response:
            return Response({"found": self.get_object().name})

        view = type("_View", (SelectorRetrieveView,), {"spec": _detail(), "post": post})

        response = view.as_view()(factory.post("/"), pk=str(ada.pk))

        assert response.status_code == 200
        assert response.data == {"found": "Ada"}

    def test_with_no_spec_it_retrieves_as_drf_does(self, ada: Author) -> None:
        view = type(
            "_View",
            (SelectorRetrieveView,),
            {"queryset": Author.objects.all(), "serializer_class": AuthorSerializer},
        )

        response = view.as_view()(factory.get("/"), pk=ada.pk)

        assert response.status_code == 200
        assert response.data["name"] == "Ada"
