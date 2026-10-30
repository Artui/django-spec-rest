"""A kernel spec set on a view's ``spec``, served by the kernel's own ``dispatch``.

The views part from the drfs path at one predicate, inside
``dispatch_mutation_for_spec`` and ``dispatch_selector_for_spec``. Every spec
here is the kernel's own ``ServiceSpec`` or ``SelectorSpec``, with the DRF seats
``SerializerValidator`` and ``SerializerPresenter``, and every test drives a
view through ``as_view()`` with nothing imported that the kernel route added,
so each one fails against a tree without it.

One of the views' own methods still reads a drfs-only field, and it is not
this module's to change, so the views here stand in for it: the retrieve and
list views render through ``get_serializer_class()``, which reads a drfs
``output_serializer``, so the selector views here set ``serializer_class``,
and what they render is DRF's, not the spec's presenter.
"""

from __future__ import annotations

import dataclasses
from typing import Any, TypedDict, cast

import django_filters
import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet
from django_filters.rest_framework import DjangoFilterBackend
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    UnknownArguments,
    Unrestricted,
    UnsetType,
)
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from django_spec_rest import UNSET, SelectorListView, SelectorRetrieveView, ServiceCreateView
from django_spec_rest.dispatch import kernel_edge
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.views.mutation.utils import dispatch_mutation_for_spec
from tests.testapp.models import Author, Post
from tests.testapp.serializers import AuthorSerializer, PostSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _AuthorInput(serializers.Serializer):
    name = serializers.CharField(max_length=20)


def _create_author(*, data: dict[str, Any]) -> Author:
    return Author.objects.create(name=data["name"])


_CREATE = ServiceSpec(
    service=_create_author,
    permissions=_OPEN,
    validator=SerializerValidator(_AuthorInput),
    presenter=SerializerPresenter(AuthorSerializer),
)


class _CreateView(ServiceCreateView):
    """A create view over a kernel spec."""

    spec = _CREATE


def _view(spec: ServiceSpec, base: type[_CreateView] = _CreateView) -> Any:
    return type("_View", (base,), {"spec": spec}).as_view()


def _post(view: Any, body: Any, *, format: str = "json", **kwargs: Any) -> Response:
    return view(factory.post("/", body, format=format), **kwargs)


class TestACreateView:
    def test_creates_and_presents_through_the_spec_s_presenter(self) -> None:
        response = _post(_view(_CREATE), {"name": "Ada"})
        assert response.status_code == 201
        assert response.data == {"id": Author.objects.get().pk, "name": "Ada"}

    def test_the_view_s_own_classes_refuse_before_the_spec_runs(self) -> None:
        """A kernel spec's checks are its ``permissions``, asked by ``dispatch``;
        the view's own ``permission_classes`` are DRF's, asked first."""

        class _Deny(BasePermission):
            def has_permission(self, request: Any, view: Any) -> bool:
                return False

        view = type("_View", (_CreateView,), {"permission_classes": [_Deny]}).as_view()
        assert _post(view, {"name": "Ada"}).status_code == 403
        assert not Author.objects.exists()

    def test_a_kernel_spec_passes_as_view(self) -> None:
        """``as_view()`` checks no drfs field on a kernel spec, which has none of
        them; a kernel spec well declared passes the checks it does run."""
        assert callable(_CreateView.as_view())

    def test_a_kernel_selector_spec_on_a_mutation_view_is_refused_at_as_view(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="is a SelectorSpec"):
            type("_View", (_CreateView,), {"spec": _ONE}).as_view()

    def test_the_serializer_s_refusal_is_drf_s_400(self) -> None:
        response = _post(_view(_CREATE), {"name": "x" * 21})
        assert response.status_code == 400
        assert response.data["name"][0].code == "max_length"
        assert not Author.objects.exists()

    def test_nothing_to_present_answers_204(self) -> None:
        spec = ServiceSpec(
            service=lambda: None, permissions=_OPEN, presenter=SerializerPresenter(AuthorSerializer)
        )
        response = _post(_view(spec), {})
        assert response.status_code == 204
        assert response.data is None

    def test_a_body_under_a_204_default_answers_200(self) -> None:
        """A ``204`` carries no body, so a value to present goes out under ``200``."""

        class _Destroy(APIView):
            def post(self, request: Any) -> Response:
                return dispatch_mutation_for_spec(
                    self,
                    request,
                    _CREATE,
                    instance=None,
                    default_status=204,
                    render_instance_on_none=False,
                )

        response = _post(_Destroy.as_view(), {"name": "Ada"})
        assert response.status_code == 200
        assert response.data["name"] == "Ada"

    def test_a_body_that_is_no_object_is_refused_as_a_whole(self) -> None:
        response = _post(_view(_CREATE), [{"name": "Ada"}])
        assert response.status_code == 400
        assert response.data == {"detail": "The body must be an object; got list."}


class TestTheCallsContext:
    def test_the_view_s_request_and_view_reach_the_service_and_its_serializer(self) -> None:
        seen: dict[str, Any] = {}

        class _Input(serializers.Serializer):
            name = serializers.CharField()

            def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
                seen["serializer"] = (self.context["request"], self.context["view"])
                return attrs

        def service(*, data: dict[str, Any], request: Any, view: Any, call_context: Any) -> None:
            seen["service"] = (request, view)
            seen["call_context"] = call_context

        spec = ServiceSpec(
            service=service, permissions=_OPEN, validator=SerializerValidator(_Input)
        )
        response = _post(_view(spec), {"name": "Ada"})
        assert response.status_code == 204
        request, view = seen["service"]
        assert isinstance(view, _CreateView)
        assert request is view.request
        assert seen["serializer"] == (request, view)
        # The request's one dict, the view's own, holding DRF's standard entries.
        assert seen["call_context"] is view._call_context
        assert seen["call_context"]["request"] is request
        assert seen["call_context"]["view"] is view


class TestAnUndeclaredKeyByDefault:
    """The edge dispatches under ``IGNORE``: a key no parameter declares is dropped, as
    DRF drops a key no serializer field declares, so a client sending a row back with
    its ``id`` is not refused, and neither is a body of nothing but such keys."""

    @pytest.mark.parametrize(
        ("body", "data"),
        [({"title": "t", "id": 1}, {"title": "t"}), ({"nope": 1}, {})],
        ids=["beside-a-field", "alone"],
    )
    def test_an_undeclared_body_key_is_dropped_by_default(
        self, body: dict[str, Any], data: dict[str, Any]
    ) -> None:
        received: list[dict[str, Any]] = []

        class _Input(serializers.Serializer):
            title = serializers.CharField(required=False)

        spec = ServiceSpec(
            service=lambda *, data: received.append(data),
            permissions=_OPEN,
            validator=SerializerValidator(_Input),
        )
        response = _post(_view(spec), body)
        assert response.status_code == 204, response.data
        assert received == [data]

    def test_an_undeclared_query_key_is_dropped_by_default(self) -> None:
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=lambda: Post.objects.all(),
            permissions=_OPEN,
        )
        cls = type("_View", (SelectorListView,), {"spec": spec, "serializer_class": PostSerializer})
        response = cls.as_view()(factory.get("/?nope=1"))
        assert response.status_code == 200, response.data
        assert response.data == []


class TestNothingIsStripped:
    @pytest.mark.parametrize("key", ["request", "serializer"])
    def test_a_key_no_field_declares_is_an_unknown_argument_under_reject(
        self, key: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", UnknownArguments.REJECT)
        response = _post(_view(_CREATE), {"name": "Ada", key: "x"})
        assert response.status_code == 400
        assert key in response.data
        assert "Unknown argument." in str(response.data[key])
        assert not Author.objects.exists()

    @pytest.mark.parametrize("key", ["request", "serializer"])
    def test_a_key_no_field_declares_is_dropped_under_ignore(
        self, key: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The kernel drops it, never the edge: the edge still strips nothing."""
        monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", UnknownArguments.IGNORE)
        response = _post(_view(_CREATE), {"name": "Ada", key: "x"})
        assert response.status_code == 201, response.data
        assert response.data == {"id": Author.objects.get().pk, "name": "Ada"}


class TestASeedNamedFieldValidatesFromTheBody:
    @pytest.mark.parametrize("name", ["user", "result", "serializer"])
    def test_a_writable_field_named_like_a_seed_validates_into_data(self, name: str) -> None:
        received: dict[str, Any] = {}
        fields = {
            "title": serializers.CharField(),
            name: serializers.IntegerField(),
        }
        named = type("_Input", (serializers.Serializer,), fields)

        def service(*, data: dict[str, Any], user: Any) -> None:
            received["data"] = data
            received["user"] = user

        principal = User.objects.create(username="ada")
        spec = ServiceSpec(service=service, permissions=_OPEN, validator=SerializerValidator(named))
        request = factory.post("/", {"title": "t", name: "7"}, format="json")
        force_authenticate(request, user=principal)
        response = _view(spec)(request)
        assert response.status_code == 204, response.data
        assert received["data"] == {"title": "t", name: 7}
        # The seed keeps its own value: the principal, never the body's.
        assert received["user"] == principal

    def test_a_seed_named_field_validates_from_a_form_body(self) -> None:
        """A form body's seed-named field is handed to the serializer as its one
        value, as DRF reads a form, so the serializer coerces it."""

        class _Input(serializers.Serializer):
            title = serializers.CharField()
            user = serializers.IntegerField()

        received: dict[str, Any] = {}
        spec = ServiceSpec(
            service=lambda *, data: received.update(data),
            permissions=_OPEN,
            validator=SerializerValidator(_Input),
        )
        response = _post(_view(spec), {"title": "t", "user": "7"}, format="multipart")
        assert response.status_code == 204, response.data
        assert received == {"title": "t", "user": 7}

    def test_a_seed_named_field_the_serializer_refuses_is_drf_s_400(self) -> None:
        class _Input(serializers.Serializer):
            title = serializers.CharField()
            user = serializers.IntegerField()

        spec = ServiceSpec(
            service=lambda: None, permissions=_OPEN, validator=SerializerValidator(_Input)
        )
        response = _post(_view(spec), {"title": "t", "user": "nope"})
        assert response.status_code == 400
        assert response.data["user"][0].code == "invalid"

    def test_a_declared_capture_outranks_the_body_beside_a_seed_named_field(self) -> None:
        """Where the serializer is handed what the request sent, for a field the
        kernel cannot take, a declared capture still goes over the body, as it
        does on a body with no such field: the client never moves the route."""

        class _Input(serializers.Serializer):
            author = serializers.IntegerField()
            user = serializers.IntegerField()

        received: dict[str, Any] = {}
        spec = ServiceSpec(
            service=lambda *, data: received.update(data),
            permissions=_OPEN,
            validator=SerializerValidator(_Input),
        )
        response = _post(_view(spec), {"author": 9, "user": 7}, author="4")
        assert response.status_code == 204, response.data
        assert received == {"author": 4, "user": 7}

    def test_a_body_with_no_seed_named_field_keeps_the_input_data_provider(self) -> None:
        """The serializer binds what the kernel hands it, ``input_data``'s values
        merged in."""

        class _Input(serializers.Serializer):
            title = serializers.CharField()
            user = serializers.IntegerField(required=False)

        received: dict[str, Any] = {}
        spec = ServiceSpec(
            service=lambda *, data: received.update(data),
            permissions=_OPEN,
            validator=SerializerValidator(_Input),
            input_data=lambda: {"title": "from the server"},
        )
        response = _post(_view(spec), {"title": "from the client"})
        assert response.status_code == 204, response.data
        assert received == {"title": "from the server"}

    def test_input_data_outranks_the_body_beside_a_seed_named_field(self) -> None:
        """A body sending a field the kernel cannot take still has the server's
        values over the client's: the serializer binds the kernel's checked
        arguments, ``input_data``'s merged in, over that field's value alone."""

        class _Input(serializers.Serializer):
            title = serializers.CharField()
            user = serializers.IntegerField(required=False)

        received: dict[str, Any] = {}
        spec = ServiceSpec(
            service=lambda *, data: received.update(data),
            permissions=_OPEN,
            validator=SerializerValidator(_Input),
            input_data=lambda: {"title": "from the server"},
        )
        response = _post(_view(spec), {"title": "from the client", "user": 7})
        assert response.status_code == 204, response.data
        assert received == {"title": "from the server", "user": 7}


class _UserPk(serializers.Serializer):
    title = serializers.CharField(required=False)
    user = serializers.IntegerField(required=False)


class _OwnsTitle(TypedDict):
    title: str


class _OwnsUser(TypedDict):
    user: int


class _MayFillUser(TypedDict):
    user: int | UnsetType


def _declines_title() -> _OwnsTitle:
    return cast(_OwnsTitle, {"title": UNSET})


def _declines_owned_user() -> _OwnsUser:
    return cast(_OwnsUser, {"user": UNSET})


def _declines_user() -> _MayFillUser:
    return {"user": UNSET}


def _user_pk(*, user: Any) -> dict[str, Any]:
    return {"user": user.pk}


def _post_as(principal: User, spec: ServiceSpec, body: Any) -> tuple[Response, dict[str, Any]]:
    """Post ``body`` as ``principal`` to ``spec``'s create view, and what its service received."""
    received: dict[str, Any] = {}
    spec = dataclasses.replace(spec, service=lambda *, data: received.update(data))
    request = factory.post("/", body, format="json")
    force_authenticate(request, user=principal)
    return _view(spec)(request), received


class TestInputDataOverASeedNamedField:
    """The kernel hands a Validator only the ``input_data`` keys its parameters
    declare, and a seed-named field is none of them, so the edge reads the
    provider's answer for such a field as the provider gives it and binds it
    over the client's, the provider still called once."""

    def _spec(self, input_data: Any) -> ServiceSpec:
        return ServiceSpec(
            service=lambda: None,
            permissions=_OPEN,
            validator=SerializerValidator(_UserPk),
            input_data=input_data,
        )

    def test_the_provider_s_value_outranks_the_client_s(self) -> None:
        principal = User.objects.create(username="ada")
        other = User.objects.create(username="bo")
        calls: list[Any] = []

        def user_pk(*, user: Any) -> dict[str, Any]:
            calls.append(user)
            return {"user": user.pk}

        response, received = _post_as(
            principal, self._spec(user_pk), {"title": "t", "user": other.pk}
        )
        assert response.status_code == 204, response.data
        assert received == {"title": "t", "user": principal.pk}
        assert calls == [principal]

    def test_the_provider_s_value_reaches_a_body_leaving_the_field_out(self) -> None:
        principal = User.objects.create(username="ada")
        response, received = _post_as(principal, self._spec(_user_pk), {"title": "t"})
        assert response.status_code == 204, response.data
        assert received == {"title": "t", "user": principal.pk}

    def test_the_view_s_spec_presents_what_its_twin_returned(self) -> None:
        """The edge dispatches the spec's recording twin, and the view presents
        the result through its own spec, whose presenter the twin shares."""
        principal = User.objects.create(username="ada")

        def create(*, data: dict[str, Any]) -> Author:
            return Author.objects.create(name=f"{data['title']}-{data['user']}")

        spec = ServiceSpec(
            service=create,
            permissions=_OPEN,
            validator=SerializerValidator(_UserPk),
            input_data=_user_pk,
            presenter=SerializerPresenter(AuthorSerializer),
        )
        request = factory.post("/", {"title": "t", "user": 7}, format="json")
        force_authenticate(request, user=principal)
        response = _view(spec)(request)
        assert response.status_code == 201, response.data
        assert response.data == {"id": Author.objects.get().pk, "name": f"t-{principal.pk}"}

    def test_an_owned_field_it_declines_is_absent_not_the_client_s(self) -> None:
        principal = User.objects.create(username="ada")
        response, received = _post_as(
            principal, self._spec(_declines_owned_user), {"title": "t", "user": 7}
        )
        assert response.status_code == 204, response.data
        assert received == {"title": "t"}

    def test_a_declinable_field_it_declines_stays_the_client_s(self) -> None:
        principal = User.objects.create(username="ada")
        response, received = _post_as(
            principal, self._spec(_declines_user), {"title": "t", "user": 7}
        )
        assert response.status_code == 204, response.data
        assert received == {"title": "t", "user": 7}

    @pytest.mark.parametrize("extra", [{}, {"user": 7}], ids=["plain", "seed-named"])
    def test_an_owned_parameter_it_declines_never_takes_the_client_s_value(
        self, extra: dict[str, Any]
    ) -> None:
        """Beside a seed-named field too: the serializer binds the kernel's
        checked arguments, which hold no ``title``, and nothing of the body but
        that field."""
        principal = User.objects.create(username="ada")
        response, received = _post_as(
            principal, self._spec(_declines_title), {"title": "from the client", **extra}
        )
        assert response.status_code == 204, response.data
        assert received == extra


class TestTheArgumentsAreReadAsTheKernelReadsAWire:
    def test_a_form_body_is_read_flat_and_coerced(self) -> None:
        class _Input(serializers.Serializer):
            title = serializers.CharField()
            views = serializers.IntegerField(required=False)
            published = serializers.BooleanField(required=False)

        received: dict[str, Any] = {}
        spec = ServiceSpec(
            service=lambda *, data: received.update(data),
            permissions=_OPEN,
            validator=SerializerValidator(_Input),
        )
        response = _post(
            _view(spec),
            {"title": "t", "views": "3", "published": "", "csrfmiddlewaretoken": "x"},
            format="multipart",
        )
        assert response.status_code == 204, response.data
        # ``views`` coerced to the integer it declares, a blank boolean absent,
        # and Django's CSRF field never an argument.
        assert received == {"title": "t", "views": 3}

    def test_a_form_s_true_is_a_boolean(self) -> None:
        """The kernel's typed check takes an integer's ``"3"`` as sent, so a
        boolean is what holds the form body's coercion."""

        class _Input(serializers.Serializer):
            published = serializers.BooleanField()

        received: dict[str, Any] = {}
        spec = ServiceSpec(
            service=lambda *, data: received.update(data),
            permissions=_OPEN,
            validator=SerializerValidator(_Input),
        )
        response = _post(_view(spec), {"published": "true"}, format="multipart")
        assert response.status_code == 204, response.data
        assert received == {"published": True}

    def test_a_json_body_is_not_read_as_flat_strings(self) -> None:
        """A JSON ``"true"`` is a string, typed by the client, and reaches the
        kernel's typed check as one, where a form's ``"true"`` is coerced.

        The kernel's check answers before the serializer does, so DRF, which
        would read ``"true"`` as ``True``, is never asked. A lenient Validator,
        whose typed check leaves the serializer's coercion to DRF, reverses this."""

        class _Input(serializers.Serializer):
            published = serializers.BooleanField()

        spec = ServiceSpec(
            service=lambda: None, permissions=_OPEN, validator=SerializerValidator(_Input)
        )
        response = _post(_view(spec), {"published": "true"})
        assert response.status_code == 400
        assert str(response.data["published"][0]) == "Expected a boolean."

    def test_a_declared_capture_is_coerced_and_an_undeclared_one_is_no_argument(self) -> None:
        received: dict[str, Any] = {}
        seen_kwargs: dict[str, Any] = {}

        class _SeesKwargs(BasePermission):
            def has_permission(self, request: Any, view: Any) -> bool:
                seen_kwargs.update(view.kwargs)
                return True

        def service(*, data: dict[str, Any], author: int) -> None:
            received.update(data, author=author)

        spec = ServiceSpec(
            service=service,
            permissions=_OPEN,
            reads=Parameters.of(Parameter("author", "integer")),
            validator=SerializerValidator(_AuthorInput),
        )
        view = type("_View", (_CreateView,), {"spec": spec, "permission_classes": [_SeesKwargs]})
        response = _post(view.as_view(), {"name": "Ada"}, author="4", tenant="acme")
        assert response.status_code == 204, response.data
        assert received == {"name": "Ada", "author": 4}
        assert seen_kwargs == {"author": "4", "tenant": "acme"}

    def test_a_capture_outranks_the_body(self) -> None:
        received: dict[str, Any] = {}
        spec = ServiceSpec(
            service=lambda *, author: received.update(author=author),
            permissions=_OPEN,
            reads=Parameters.of(Parameter("author", "integer", required=True)),
        )
        response = _post(_view(spec), {"author": 9}, author="4")
        assert response.status_code == 204, response.data
        assert received == {"author": 4}

    def test_a_capture_on_a_json_body_is_coerced(self) -> None:
        received: dict[str, Any] = {}
        spec = ServiceSpec(
            service=lambda *, draft: received.update(draft=draft),
            permissions=_OPEN,
            reads=Parameters.of(Parameter("draft", "boolean", required=True)),
        )
        response = _post(_view(spec), {}, draft="true")
        assert response.status_code == 204, response.data
        assert received == {"draft": True}

    def test_a_capture_outranks_a_form_body(self) -> None:
        received: dict[str, Any] = {}
        spec = ServiceSpec(
            service=lambda *, author: received.update(author=author),
            permissions=_OPEN,
            reads=Parameters.of(Parameter("author", "integer", required=True)),
        )
        response = _post(_view(spec), {"author": "9"}, format="multipart", author="4")
        assert response.status_code == 204, response.data
        assert received == {"author": 4}


class TestAManySpec:
    def test_a_list_body_is_its_rows_and_its_output_selector_s_re_read_is_presented(
        self,
    ) -> None:
        """The kernel runs a ``many`` spec's output selector on what the service
        returned and presents the re-read, as on every transport."""
        reread: dict[str, Any] = {}

        def create(*, data: list[dict[str, Any]]) -> list[Author]:
            return [Author.objects.create(name=row["name"]) for row in data]

        def again(*, result: list[Author]) -> QuerySet[Author]:
            reread["result"] = result
            return Author.objects.filter(pk__in=[a.pk for a in result]).order_by("-name")

        spec = ServiceSpec(
            service=create,
            permissions=_OPEN,
            many=True,
            validator=SerializerValidator(_AuthorInput),
            output_selector_spec=SelectorSpec(
                kind=SelectorKind.LIST,
                selector=again,
                permissions=_OPEN,
                presenter=SerializerPresenter(AuthorSerializer),
            ),
        )
        response = _post(_view(spec), [{"name": "Ada"}, {"name": "Bo"}])
        assert response.status_code == 201, response.data
        assert [row["name"] for row in response.data] == ["Bo", "Ada"]
        assert [a.name for a in reread["result"]] == ["Ada", "Bo"]

    def test_a_declared_capture_reaches_a_many_spec_beside_its_rows(self) -> None:
        received: dict[str, Any] = {}

        def create(*, data: list[dict[str, Any]], author: int) -> None:
            received.update(names=[row["name"] for row in data], author=author)

        spec = ServiceSpec(
            service=create,
            permissions=_OPEN,
            many=True,
            reads=Parameters.of(Parameter("author", "integer")),
            validator=SerializerValidator(_AuthorInput),
        )
        response = _post(_view(spec), [{"name": "Ada"}], author="4")
        assert response.status_code == 204, response.data
        assert received == {"names": ["Ada"], "author": 4}


class TestATargetTheViewHandsOver:
    def test_a_missing_row_the_spec_s_lookup_finds_is_404(self) -> None:
        spec = ServiceSpec(
            service=lambda *, instance: None,
            permissions=_OPEN,
            instance_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
                reads=Parameters.of(Parameter("pk", "integer", required=True)),
                permissions=_OPEN,
            ),
        )

        class _Update(APIView):
            def post(self, request: Any, **kwargs: Any) -> Response:
                return dispatch_mutation_for_spec(
                    self,
                    request,
                    spec,
                    instance=UNSET,
                    default_status=200,
                    render_instance_on_none=True,
                )

        assert _post(_Update.as_view(), {}, pk="1").status_code == 404


class _AuthorsByName(SelectorListView):
    serializer_class = AuthorSerializer


class _OneAuthor(SelectorRetrieveView):
    serializer_class = AuthorSerializer


def _get(view: type, spec: SelectorSpec, path: str = "/", **kwargs: Any) -> Response:
    cls = type("_View", (view,), {"spec": spec})
    return cls.as_view()(factory.get(path), **kwargs)


_ONE = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
    permissions=_OPEN,
)


class TestARetrieveView:
    def test_the_route_s_capture_finds_the_row(self) -> None:
        author = Author.objects.create(name="Ada")
        response = _get(_OneAuthor, _ONE, pk=str(author.pk))
        assert response.status_code == 200
        assert response.data == {"id": author.pk, "name": "Ada"}

    def test_a_kernel_selector_spec_passes_as_view(self) -> None:
        assert callable(type("_View", (_OneAuthor,), {"spec": _ONE}).as_view())

    def test_a_kernel_service_spec_on_a_selector_view_is_refused_at_as_view(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="is a ServiceSpec"):
            type("_View", (_OneAuthor,), {"spec": _CREATE}).as_view()

    def test_a_list_spec_on_a_retrieve_view_is_refused_at_as_view(self) -> None:
        spec = SelectorSpec(kind=SelectorKind.LIST, selector=Author.objects.all, permissions=_OPEN)
        with pytest.raises(ImproperlyConfigured, match="spec.kind is"):
            type("_View", (_OneAuthor,), {"spec": spec}).as_view()

    def test_the_selector_s_call_context_is_the_view_s_own(self) -> None:
        author = Author.objects.create(name="Ada")
        seen: dict[str, Any] = {}

        def one(*, pk: int, call_context: Any, view: Any) -> Author:
            seen.update(call_context=call_context, view=view)
            return Author.objects.get(pk=pk)

        spec = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=one,
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
            permissions=_OPEN,
        )
        assert _get(_OneAuthor, spec, pk=str(author.pk)).status_code == 200
        assert seen["call_context"] is seen["view"]._call_context

    def test_a_missing_row_is_404(self) -> None:
        assert _get(_OneAuthor, _ONE, pk="1").status_code == 404

    def test_a_kernel_retrieve_asks_the_view_s_object_permission(self) -> None:
        author = Author.objects.create(name="Ada")

        class _NotThisRow(BasePermission):
            def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
                return obj.pk != author.pk

        cls = type("_View", (_OneAuthor,), {"spec": _ONE, "permission_classes": [_NotThisRow]})
        response = cls.as_view()(factory.get("/"), pk=str(author.pk))
        assert response.status_code == 403


class TestAListView:
    def test_the_query_string_is_read_by_the_declaration(self) -> None:
        Author.objects.create(name="Ada")
        kept = Author.objects.create(name="Bo")
        other = Author.objects.create(name="Cy")
        received: dict[str, Any] = {}

        def authors(*, ids: list[int], named: str = "") -> QuerySet[Author]:
            received.update(ids=ids, named=named)
            return Author.objects.filter(pk__in=ids).order_by("pk")

        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=authors,
            reads=Parameters.of(
                Parameter("ids", "array", items="integer", required=True),
                Parameter("named", "string", required=False),
            ),
            permissions=_OPEN,
        )
        response = _get(_AuthorsByName, spec, f"/?ids={kept.pk},{other.pk}&named=")
        assert response.status_code == 200, response.data
        assert [row["name"] for row in response.data] == ["Bo", "Cy"]
        # A comma list of integers is its elements, coerced; a blank string is
        # one a plain string can take.
        assert received == {"ids": [kept.pk, other.pk], "named": ""}

    def test_an_undeclared_query_key_is_an_unknown_argument_under_reject(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", UnknownArguments.REJECT)
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=lambda: Post.objects.all(),
            permissions=_OPEN,
        )
        cls = type("_View", (SelectorListView,), {"spec": spec, "serializer_class": PostSerializer})
        response = cls.as_view()(factory.get("/?nope=1"))
        assert response.status_code == 400
        assert "Unknown argument." in str(response.data["nope"])

    def test_a_query_string_s_true_is_a_boolean(self) -> None:
        received: dict[str, Any] = {}

        def authors(*, published: bool) -> QuerySet[Author]:
            received.update(published=published)
            return Author.objects.none()

        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=authors,
            reads=Parameters.of(Parameter("published", "boolean", required=True)),
            permissions=_OPEN,
        )
        response = _get(_AuthorsByName, spec, "/?published=true")
        assert response.status_code == 200, response.data
        assert received == {"published": True}

    def test_a_filter_set_beside_django_filter_s_backend_is_refused_at_as_view(self) -> None:
        """Both apply a ``FilterSet`` to the list, so the list would be
        filtered twice; with no such backend the spec mounts."""

        class _ByName(django_filters.FilterSet):
            class Meta:
                model = Author
                fields = ["name"]

        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=Author.objects.all,
            permissions=_OPEN,
            filter_set=_ByName,
        )
        assert callable(type("_View", (_AuthorsByName,), {"spec": spec}).as_view())
        backed = {"spec": spec, "filter_backends": [DjangoFilterBackend]}
        with pytest.raises(ImproperlyConfigured, match="filtered twice"):
            type("_View", (_AuthorsByName,), backed).as_view()
