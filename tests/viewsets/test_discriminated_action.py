from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django_service_specs import (
    AdditionalInputRequired,
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceConflict,
    ServiceSpec,
    ServiceValidationError,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.exceptions import APIException, NotAuthenticated
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.viewsets import GenericViewSet

from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.types.discriminated_action import DiscriminatedAction
from django_spec_rest.views.utils import view_call_context
from django_spec_rest.viewsets.decorators.service_action import service_action
from django_spec_rest.viewsets.service_viewset import ServiceViewSet
from tests.testapp.models import Author, Post

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()

_OPEN = (Unrestricted(),)
EDITORS_ONLY = "Editors only."
ADMINS_ONLY = "Admins only."
SIGN_IN = "Authentication credentials were not provided."
CHALLENGE = 'Basic realm="api"'


class _Allow(PermissionCheck):
    """Admits the named callers, counting each time it is asked."""

    def __init__(self, *names: str, message: str = EDITORS_ONLY) -> None:
        self.names = names
        self.message = message
        self.asked = 0

    def has_permission(self, principal: Any, spec: Any) -> bool:
        self.asked += 1
        return getattr(principal, "username", None) in self.names


class _IsEditor(BasePermission):
    message = EDITORS_ONLY

    def has_permission(self, request: Any, view: Any) -> bool:
        return getattr(request.user, "username", None) == "editor"


class _Raises(PermissionCheck):
    """A check refusing by raising rather than answering ``False``."""

    def __init__(self, raised: Exception) -> None:
        self.raised = raised

    def has_permission(self, principal: Any, spec: Any) -> bool:
        raise self.raised


class _OwnerOnly(PermissionCheck):
    """A check that reads the arguments, so asked with none it cannot answer."""

    message = "Owners only."

    def has_permission(self, principal: Any, spec: Any, *, arguments: Any) -> bool:
        return arguments["owner"] == "me"


class _PasswordIn(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()


class _TokenIn(serializers.Serializer):
    token = serializers.CharField()


class _WhoOut(serializers.Serializer):
    who = serializers.CharField()


class _ViaOut(serializers.Serializer):
    via = serializers.CharField()


def _password(*, data: dict[str, Any]) -> dict[str, str]:
    return {"who": data["email"]}


def _token(*, data: dict[str, Any]) -> dict[str, str]:
    return {"via": data["token"]}


def _by_kind(*, data: Any) -> str:
    return data["kind"]


def _password_spec(permissions: Any = _OPEN) -> ServiceSpec:
    return ServiceSpec(
        service=_password,
        permissions=permissions,
        validator=SerializerValidator(_PasswordIn),
        presenter=SerializerPresenter(_WhoOut),
    )


def _token_spec(permissions: Any = _OPEN) -> ServiceSpec:
    return ServiceSpec(
        service=_token,
        permissions=permissions,
        validator=SerializerValidator(_TokenIn),
        presenter=SerializerPresenter(_ViaOut),
    )


def _login(discriminator: Any = _by_kind, password: Any = _OPEN, token: Any = _OPEN) -> Any:
    return DiscriminatedAction(
        discriminator,
        {"password": _password_spec(password), "token": _token_spec(token)},
    )


def _create_view(action: Any, authentication: tuple[type, ...] = ()) -> Any:
    attrs = {
        "action_specs": {"create": action},
        "permission_classes": [AllowAny],
        "authentication_classes": list(authentication),
    }
    return type("_ViewSet", (ServiceViewSet,), attrs).as_view({"post": "create"})


def _post(view: Any, body: Any, *, username: str | None = None, **kwargs: Any) -> Response:
    request = factory.post("/", body, format="json")
    if username is not None:
        force_authenticate(request, User.objects.create(username=username))
    response = view(request, **kwargs)
    response.render()
    return response


GOOD_PASSWORD = {"kind": "password", "email": "a@b.co", "password": "x"}
GOOD_TOKEN = {"kind": "token", "token": "t"}


class TestEachVariantRunsItsOwn:
    def test_validator_and_presenter(self) -> None:
        view = _create_view(_login())
        assert _post(view, GOOD_PASSWORD).data == {"who": "a@b.co"}
        assert _post(view, GOOD_TOKEN).data == {"via": "t"}

    def test_refusal_of_its_own_shape(self) -> None:
        view = _create_view(_login())
        password = _post(view, {"kind": "password", "email": "nope", "password": "x"})
        assert (password.status_code, set(password.data)) == (400, {"email"})
        token = _post(view, {"kind": "token"})
        assert (token.status_code, set(token.data)) == (400, {"token"})

    def test_checks(self) -> None:
        action = _login(token=(_Allow("editor"),))
        view = _create_view(action)
        assert _post(view, GOOD_PASSWORD, username="ada").status_code == 201
        assert _post(view, GOOD_TOKEN, username="bea").status_code == 403
        assert _post(view, GOOD_TOKEN, username="editor").status_code == 201

    def test_a_key_the_chosen_variant_does_not_declare_is_dropped_as_on_any_spec(self) -> None:
        seen: list[dict[str, Any]] = []

        def service(*, data: dict[str, Any]) -> None:
            seen.append(data)

        action = DiscriminatedAction(
            _by_kind,
            {
                "token": ServiceSpec(
                    service=service, permissions=_OPEN, validator=_token_validator()
                )
            },
        )
        _post(_create_view(action), GOOD_TOKEN)
        assert seen == [{"token": "t"}]


def _token_validator() -> SerializerValidator:
    return SerializerValidator(_TokenIn)


class _NameIn(serializers.Serializer):
    name = serializers.CharField()


class _AuthorOut(serializers.ModelSerializer):
    class Meta:
        model = Author
        fields = ("id", "name")


_BY_PK = Parameters.of(Parameter("pk", "integer", required=True))


def _row(queryset: Any = None) -> SelectorSpec:
    def select(*, pk: int) -> Any:
        return (Author.objects.all() if queryset is None else queryset()).filter(pk=pk).first()

    return SelectorSpec(kind=SelectorKind.RETRIEVE, selector=select, reads=_BY_PK)


def _rename(*, instance: Author, data: dict[str, Any]) -> Author:
    instance.name = data["name"]
    instance.save(update_fields=["name"])
    return instance


def _shout(*, instance: Author, data: dict[str, Any]) -> Author:
    instance.name = data["name"].upper()
    instance.save(update_fields=["name"])
    return instance


def _detail_action() -> DiscriminatedAction:
    return DiscriminatedAction(
        lambda *, request: request.query_params.get("how", "rename"),
        {
            "rename": ServiceSpec(
                service=_rename,
                permissions=_OPEN,
                validator=SerializerValidator(_NameIn),
                presenter=SerializerPresenter(_AuthorOut),
                instance_selector_spec=_row(),
            ),
            # Its own target selector: a row whose name starts with "a", no other.
            "shout": ServiceSpec(
                service=_shout,
                permissions=_OPEN,
                validator=SerializerValidator(_NameIn),
                presenter=SerializerPresenter(_AuthorOut),
                instance_selector_spec=_row(lambda: Author.objects.filter(name__startswith="a")),
            ),
        },
    )


class TestADetailVariant:
    @pytest.mark.parametrize(
        ("method", "action_name"), [("put", "update"), ("patch", "partial_update")]
    )
    def test_finds_the_row_with_its_own_target_selector(
        self, method: str, action_name: str
    ) -> None:
        amy = Author.objects.create(name="amy")
        bob = Author.objects.create(name="bob")

        class _ViewSet(ServiceViewSet):
            action_specs = {action_name: _detail_action()}

        view = _ViewSet.as_view({method: action_name})

        def call(path: str, pk: int) -> Any:
            return view(getattr(factory, method)(path, {"name": "cy"}, format="json"), pk=pk)

        assert call("/", amy.pk).data == {"id": amy.pk, "name": "cy"}
        amy.name = "amy"
        amy.save()
        assert call("/?how=shout", amy.pk).data == {"id": amy.pk, "name": "CY"}
        # The other variant's selector would find this row.
        assert call("/?how=shout", bob.pk).status_code == 404
        assert call("/", bob.pk).status_code == 200

    def test_a_destroy_chooses_and_answers_as_a_destroy(self) -> None:
        kept = Author.objects.create(name="kept")
        gone = Author.objects.create(name="gone")

        def delete(*, instance: Author) -> None:
            instance.delete()

        def refuse(*, instance: Author) -> None:
            raise ServiceConflict("Kept.")

        action = DiscriminatedAction(
            lambda *, request: request.query_params["how"],
            {
                "delete": ServiceSpec(
                    service=delete, permissions=_OPEN, instance_selector_spec=_row()
                ),
                "refuse": ServiceSpec(
                    service=refuse, permissions=_OPEN, instance_selector_spec=_row()
                ),
            },
        )

        class _ViewSet(ServiceViewSet):
            action_specs = {"destroy": action}

        view = _ViewSet.as_view({"delete": "destroy"})
        assert view(factory.delete("/?how=refuse"), pk=kept.pk).status_code == 409
        answer = view(factory.delete("/?how=delete"), pk=gone.pk)
        assert (answer.status_code, answer.data) == (204, None)
        assert list(Author.objects.all()) == [kept]

    def test_a_destroy_returning_nothing_answers_204_beside_a_presenter(self) -> None:
        row = Author.objects.create(name="amy")

        def delete(*, instance: Author) -> None:
            instance.delete()

        action = DiscriminatedAction(
            lambda: "delete",
            {
                "delete": ServiceSpec(
                    service=delete,
                    permissions=_OPEN,
                    presenter=SerializerPresenter(_AuthorOut),
                    instance_selector_spec=_row(),
                )
            },
        )

        class _ViewSet(ServiceViewSet):
            action_specs = {"destroy": action}

        answer = _ViewSet.as_view({"delete": "destroy"})(factory.delete("/"), pk=row.pk)
        assert (answer.status_code, answer.data) == (204, None)

    def test_an_update_returning_nothing_presents_its_row(self) -> None:
        row = Author.objects.create(name="amy")

        def touch(*, instance: Author, data: dict[str, Any]) -> None: ...

        action = DiscriminatedAction(
            lambda: "touch",
            {
                "touch": ServiceSpec(
                    service=touch,
                    permissions=_OPEN,
                    validator=SerializerValidator(_NameIn),
                    presenter=SerializerPresenter(_AuthorOut),
                    instance_selector_spec=_row(),
                )
            },
        )

        class _ViewSet(ServiceViewSet):
            action_specs = {"update": action}

        view = _ViewSet.as_view({"put": "update"})
        answer = view(factory.put("/", {"name": "x"}, format="json"), pk=row.pk)
        assert (answer.status_code, answer.data) == (200, {"id": row.pk, "name": "amy"})

    def test_a_patch_over_the_update_entry_is_partial_and_a_put_is_not(self) -> None:
        class _TwoFields(serializers.Serializer):
            name = serializers.CharField()
            motto = serializers.CharField()

        row = Author.objects.create(name="amy")

        def keep(*, instance: Author, data: dict[str, Any]) -> Author:
            return instance

        action = DiscriminatedAction(
            lambda: "keep",
            {
                "keep": ServiceSpec(
                    service=keep,
                    permissions=_OPEN,
                    validator=SerializerValidator(_TwoFields),
                    presenter=SerializerPresenter(_AuthorOut),
                    instance_selector_spec=_row(),
                )
            },
        )

        class _ViewSet(ServiceViewSet):
            action_specs = {"update": action}

        view = _ViewSet.as_view({"put": "update", "patch": "partial_update"})
        partial = factory.patch("/", {"name": "x"}, format="json")
        assert view(partial, pk=row.pk).status_code == 200
        whole = factory.put("/", {"name": "x"}, format="json")
        answer = view(whole, pk=row.pk)
        assert (answer.status_code, set(answer.data)) == (400, {"motto"})


class _PostIn(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    body = serializers.CharField()


class _PostOut(serializers.ModelSerializer):
    class Meta:
        model = Post
        fields = ("id", "title")


class TestAPatchVariantOverAList:
    @staticmethod
    def _view() -> Any:
        def bulk(*, data: list[dict[str, Any]]) -> list[Post]:
            rows = []
            for row in data:
                Post.objects.filter(pk=row["id"]).update(title=row["title"])
                rows.append(Post.objects.get(pk=row["id"]))
            return rows

        def one(*, instance: Author, data: dict[str, Any]) -> Author:
            instance.name = data["name"]
            instance.save(update_fields=["name"])
            return instance

        action = DiscriminatedAction(
            lambda *, data: "bulk" if isinstance(data, list) else "one",
            {
                "bulk": ServiceSpec(
                    service=bulk,
                    permissions=_OPEN,
                    validator=SerializerValidator(_PostIn),
                    presenter=SerializerPresenter(_PostOut),
                    many=True,
                    atomic=False,
                ),
                "one": ServiceSpec(
                    service=one,
                    permissions=_OPEN,
                    validator=SerializerValidator(_NameIn),
                    presenter=SerializerPresenter(_AuthorOut),
                    instance_selector_spec=_row(),
                ),
            },
        )

        class _ViewSet(ServiceViewSet):
            action_specs = {"partial_update": action}

        return _ViewSet.as_view({"patch": "partial_update"})

    def test_a_list_body_is_its_rows_each_partial(self) -> None:
        post = Post.objects.create(title="old")
        # ``body`` is required by the serializer and absent from the row.
        request = factory.patch("/", [{"id": post.pk, "title": "new"}], format="json")
        answer = self._view()(request, pk=post.pk)
        assert (answer.status_code, answer.data) == (200, [{"id": post.pk, "title": "new"}])

    def test_the_other_variant_of_the_same_route_still_finds_its_row(self) -> None:
        row = Author.objects.create(name="amy")
        request = factory.patch("/", {"name": "new"}, format="json")
        answer = self._view()(request, pk=row.pk)
        assert (answer.status_code, answer.data) == (200, {"id": row.pk, "name": "new"})


class TestAsAServiceAction:
    def test_a_list_action_runs_the_chosen_variant_at_200(self) -> None:
        class _ViewSet(ServiceViewSet):
            @service_action(_login(), methods=["post"])
            def login(self, request: Any) -> None:
                """Stubbed."""

        view = _ViewSet.as_view({"post": "login"})
        answer = _post(view, GOOD_TOKEN)
        assert (answer.status_code, answer.data) == (200, {"via": "t"})

    def test_a_detail_action_finds_its_row_on_drf_s_own_viewset(self) -> None:
        row = Author.objects.create(name="amy")

        class _ViewSet(GenericViewSet):
            @service_action(_detail_action(), detail=True, methods=["post"])
            def rename(self, request: Any, pk: int) -> None:
                """Stubbed."""

        view = _ViewSet.as_view({"post": "rename"})
        answer = view(factory.post("/?how=shout", {"name": "x"}, format="json"), pk=row.pk)
        assert (answer.status_code, answer.data) == (200, {"id": row.pk, "name": "X"})

    def test_a_detail_action_returning_nothing_presents_its_row(self) -> None:
        row = Author.objects.create(name="amy")

        def touch(*, instance: Author) -> None: ...

        action = DiscriminatedAction(
            lambda: "touch",
            {
                "touch": ServiceSpec(
                    service=touch,
                    permissions=_OPEN,
                    presenter=SerializerPresenter(_AuthorOut),
                    instance_selector_spec=_row(),
                )
            },
        )

        class _ViewSet(ServiceViewSet):
            @service_action(action, detail=True, methods=["post"])
            def touch(self, request: Any, pk: int) -> None:
                """Stubbed."""

        answer = _ViewSet.as_view({"post": "touch"})(factory.post("/"), pk=row.pk)
        assert (answer.status_code, answer.data) == (200, {"id": row.pk, "name": "amy"})

    def test_a_schema_a_variant_raises_is_served_as_raised_on_any_viewset(self) -> None:
        schema = {"type": "object", "default": False}

        def ask() -> None:
            raise AdditionalInputRequired("More.", schema=schema)

        action = DiscriminatedAction(
            lambda: "ask", {"ask": ServiceSpec(service=ask, permissions=_OPEN)}
        )

        class _ViewSet(GenericViewSet):
            @service_action(action, methods=["post"])
            def login(self, request: Any) -> None:
                """Stubbed."""

        answer = _ViewSet.as_view({"post": "login"})(factory.post("/", {}, format="json"))
        assert (answer.status_code, answer.data["schema"]) == (422, schema)


class TestTheKeywordPool:
    def test_each_name_is_what_the_edge_would_read(self) -> None:
        seen: dict[str, Any] = {}

        def discriminator(*, request: Any, data: Any, user: Any, view: Any, call_context: Any):
            seen.update(request=request, data=data, user=user, view=view, context=call_context)
            return "token"

        response = _post(_create_view(_login(discriminator)), GOOD_TOKEN, username="ada")
        assert response.status_code == 201
        assert seen["data"] == GOOD_TOKEN
        assert seen["data"] is seen["request"].data
        assert seen["user"].username == "ada"
        assert seen["user"] is seen["request"].user
        assert seen["view"].action == "create"
        assert seen["context"] is view_call_context(seen["view"], seen["request"])

    def test_a_catch_all_is_handed_all_but_the_call_context(self) -> None:
        seen: dict[str, Any] = {}

        def discriminator(**kwargs: Any) -> str:
            seen.update(kwargs)
            return "token"

        _post(_create_view(_login(discriminator)), GOOD_TOKEN)
        assert set(seen) == {"request", "data", "user", "view"}

    def test_a_catch_all_naming_the_call_context_is_handed_it(self) -> None:
        seen: dict[str, Any] = {}

        def discriminator(*, call_context: Any, **kwargs: Any) -> str:
            seen.update(kwargs, call_context=call_context)
            return "token"

        _post(_create_view(_login(discriminator)), GOOD_TOKEN)
        assert set(seen) == {"request", "data", "user", "view", "call_context"}

    def test_it_declares_nothing_and_still_runs(self) -> None:
        assert _post(_create_view(_login(lambda: "token")), GOOD_TOKEN).status_code == 201

    def test_it_runs_once_per_call(self) -> None:
        calls: list[str] = []

        def discriminator(*, data: Any) -> str:
            calls.append(data["kind"])
            return data["kind"]

        _post(_create_view(_login(discriminator)), GOOD_TOKEN)
        assert calls == ["token"]


class TestTheDiscriminatorsAnswers:
    def test_a_service_validation_error_is_400(self) -> None:
        def discriminator() -> str:
            raise ServiceValidationError({"kind": ["Unknown."]})

        answer = _post(_create_view(_login(discriminator)), {})
        assert (answer.status_code, answer.data) == (400, {"kind": ["Unknown."]})

    def test_another_service_error_takes_its_own_row(self) -> None:
        def discriminator() -> str:
            raise ServiceConflict("Busy.")

        answer = _post(_create_view(_login(discriminator)), {})
        assert (answer.status_code, answer.data) == (409, {"detail": "Busy."})

    def test_an_api_exception_is_answered_as_raised(self) -> None:
        class _Teapot(APIException):
            status_code = 418
            default_detail = "Short and stout."

        def discriminator() -> str:
            raise _Teapot

        answer = _post(_create_view(_login(discriminator)), {})
        assert (answer.status_code, answer.data) == (418, {"detail": "Short and stout."})

    def test_a_401_of_its_own_passes_with_the_challenge(self) -> None:
        def discriminator() -> str:
            raise NotAuthenticated("Log in first.")

        view = _create_view(_login(discriminator), (BasicAuthentication,))
        answer = _post(view, {})
        assert (answer.status_code, answer.data["detail"], answer["WWW-Authenticate"]) == (
            401,
            "Log in first.",
            CHALLENGE,
        )

    @pytest.mark.parametrize("stray", ["nope", None, 3, ["token"]])
    def test_a_stray_answer_is_improperly_configured_naming_the_keys(self, stray: Any) -> None:
        view = _create_view(_login(lambda: stray))
        with pytest.raises(ImproperlyConfigured, match=r"\['password', 'token'\]"):
            _post(view, {})

    def test_an_unparseable_body_an_admitted_caller_sends_is_400(self) -> None:
        request = factory.post("/", b"{", content_type="application/json")
        answer = _create_view(_login())(request)
        answer.render()
        assert answer.status_code == 400


NEVER = {
    "a kernel check": lambda: _Allow(),
    "a DRF class": lambda: DRFPermissionCheck([_IsEditor]),
}
BODIES = {
    "empty": (b"{}", "application/json"),
    "well-formed": (b'{"kind": "token", "token": "t"}', "application/json"),
    "no object": (b"[1]", "application/json"),
    "unparseable": (b"{", "application/json"),
    "unsupported": (b"hello", "text/plain"),
}


class TestThePreGate:
    @pytest.mark.parametrize("check", NEVER)
    @pytest.mark.parametrize("body", BODIES)
    def test_an_anonymous_caller_every_variant_refuses_is_401_whatever_it_sends(
        self, check: str, body: str
    ) -> None:
        asked: list[bool] = []

        def discriminator(*, data: Any) -> str:
            asked.append(True)
            return "token"

        action = _login(discriminator, password=(NEVER[check](),), token=(NEVER[check](),))
        view = _create_view(action, (BasicAuthentication, SessionAuthentication))
        raw, content_type = BODIES[body]
        answer = view(factory.post("/", raw, content_type=content_type))
        answer.render()
        assert (answer.status_code, answer.data["detail"], answer["WWW-Authenticate"]) == (
            401,
            SIGN_IN,
            CHALLENGE,
        )
        assert asked == []

    def test_with_no_challenge_to_give_it_is_403_as_drf_answers_it(self) -> None:
        action = _login(password=(_Allow(),), token=(_Allow(),))
        answer = _post(_create_view(action, (SessionAuthentication,)), {})
        assert (answer.status_code, answer.data["detail"]) == (403, SIGN_IN)

    def test_a_signed_in_caller_every_variant_refuses_is_told_the_first_variant_s_message(
        self,
    ) -> None:
        action = _login(
            password=(_Allow("editor", message=EDITORS_ONLY),),
            token=(_Allow("admin", message=ADMINS_ONLY),),
        )
        answer = _post(_create_view(action), GOOD_TOKEN, username="ada")
        assert (answer.status_code, answer.data["detail"]) == (403, EDITORS_ONLY)

    def test_refused_by_the_chosen_variant_alone_is_403_with_its_message(self) -> None:
        action = _login(token=(_Allow("editor", message=ADMINS_ONLY),))
        answer = _post(_create_view(action), GOOD_TOKEN, username="ada")
        assert (answer.status_code, answer.data["detail"]) == (403, ADMINS_ONLY)

    def test_refused_by_the_chosen_variant_alone_an_anonymous_caller_is_asked_to_sign_in(
        self,
    ) -> None:
        action = _login(token=(_Allow("editor"),))
        answer = _post(_create_view(action, (BasicAuthentication,)), GOOD_TOKEN)
        assert (answer.status_code, answer["WWW-Authenticate"]) == (401, CHALLENGE)

    def test_the_chosen_variant_s_class_level_check_is_asked_twice_and_every_other_once(
        self,
    ) -> None:
        """Pre-gate and dispatch each ask the chosen variant's check; the pre-gate asks all."""
        first, second = _Allow("ada"), _Allow("ada")
        action = _login(password=(first,), token=(second,))
        assert _post(_create_view(action), GOOD_TOKEN, username="ada").status_code == 201
        assert (first.asked, second.asked) == (1, 2)

    def test_a_check_needing_the_arguments_admits_so_its_caller_sees_the_400(self) -> None:
        action = _login(token=(_OwnerOnly(),), password=(_OwnerOnly(),))
        answer = _post(_create_view(action), {"kind": "token"}, username="ada")
        assert (answer.status_code, set(answer.data)) == (400, {"token"})

    @pytest.mark.parametrize(
        "raised",
        [DjangoPermissionDenied(EDITORS_ONLY), DRFPermissionDenied(EDITORS_ONLY)],
        ids=["django", "drf"],
    )
    def test_a_check_raising_a_refusal_refuses_as_a_false_does(self, raised: Exception) -> None:
        reached: list[bool] = []

        def discriminator() -> str:
            reached.append(True)
            return "token"

        action = _login(discriminator, password=(_Raises(raised),), token=(_Raises(raised),))
        assert _post(_create_view(action), {}, username="ada").status_code == 403
        assert reached == []

    def test_a_check_raising_a_refusal_leaves_the_next_variant_to_admit(self) -> None:
        action = _login(password=(_Raises(DRFPermissionDenied(EDITORS_ONLY)),))
        assert _post(_create_view(action), GOOD_TOKEN, username="ada").status_code == 201

    def test_a_misconfigured_variant_fails_rather_than_refuses(self) -> None:
        action = DiscriminatedAction(
            lambda: "token",
            {"token": ServiceSpec(service=lambda: None, validator=_token_validator())},
        )
        with pytest.raises(ImproperlyConfigured, match="declares no permissions"):
            _post(_create_view(action), {})

    def test_a_deactivated_principal_gets_the_first_variant_s_refusal(self) -> None:
        action = _login(password=(_Allow("ada"),), token=(_Allow("ada"),))
        request = factory.post("/", {}, format="json")
        force_authenticate(request, User.objects.create(username="ada", is_active=False))
        answer = _create_view(action)(request)
        answer.render()
        assert (answer.status_code, answer.data) == (
            403,
            {"detail": "The acting principal is unavailable."},
        )

    def test_the_view_s_own_classes_are_asked_first(self) -> None:
        check = _Allow("ada")

        class _ViewSet(ServiceViewSet):
            permission_classes = [_IsEditor]
            action_specs = {"create": _login(token=(check,))}

        answer = _post(_ViewSet.as_view({"post": "create"}), GOOD_TOKEN, username="ada")
        assert (answer.status_code, check.asked) == (403, 0)
