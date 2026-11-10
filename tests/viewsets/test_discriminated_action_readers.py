from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User
from django_service_specs import (
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.renderers import BrowsableAPIRenderer, JSONRenderer
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.viewsets import GenericViewSet

from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.types.discriminated_action import DiscriminatedAction
from django_spec_rest.viewsets.action_serializer_resolver import ActionSerializerResolver
from django_spec_rest.viewsets.decorators.service_action import service_action
from django_spec_rest.viewsets.service_viewset import ServiceViewSet
from django_spec_rest.viewsets.utils import resolve_action_service_spec

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _Allow(PermissionCheck):
    message = "Named callers only."

    def __init__(self, *names: str) -> None:
        self.names = names

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return getattr(principal, "username", None) in self.names


class _OwnerOnly(PermissionCheck):
    """A check that reads the arguments, so asked with none it cannot answer."""

    def has_permission(self, principal: Any, spec: Any, *, arguments: Any) -> bool:
        return arguments["owner"] == "me"


class _AIn(serializers.Serializer):
    alpha = serializers.CharField()


class _BIn(serializers.Serializer):
    beta = serializers.IntegerField()


def _unasked() -> str:
    raise AssertionError("no request has chosen a variant here")


def _spec_a(permissions: Any = _OPEN) -> ServiceSpec:
    return ServiceSpec(
        service=lambda *, data: None, permissions=permissions, validator=SerializerValidator(_AIn)
    )


def _spec_b(permissions: Any = _OPEN) -> ServiceSpec:
    return ServiceSpec(
        service=lambda *, data: None, permissions=permissions, validator=SerializerValidator(_BIn)
    )


def _bodyless(permissions: Any = _OPEN) -> ServiceSpec:
    return ServiceSpec(service=lambda: None, permissions=permissions)


def _action(**specs: Any) -> DiscriminatedAction:
    return DiscriminatedAction(_unasked, specs or {"a": _spec_a(), "b": _spec_b()})


def _viewset(entry: Any, *, key: str = "create", **attrs: Any) -> type:
    return type("_ViewSet", (ServiceViewSet,), {"action_specs": {key: entry}, **attrs})


def _options(view: Any, username: str | None = None, **kwargs: Any) -> Any:
    request = factory.options("/")
    if username is not None:
        force_authenticate(request, User.objects.create(username=username))
    return view(request, **kwargs)


class TestRefuses:
    """``_refuses``, asked on every response through ``allowed_methods``."""

    def test_allow_names_the_method_it_serves_and_runs_no_discriminator(self) -> None:
        view = _viewset(_action()).as_view({"post": "create", "put": "update"})
        answer = _options(view)
        assert "POST" in answer["Allow"]
        # ``update`` has no entry on this route serving one.
        assert "PUT" not in answer["Allow"]

    def test_it_is_answered_for_the_wrapper_itself(self) -> None:
        instance = _viewset(_action())()
        instance.action_map = {"post": "create", "put": "update"}
        assert instance._refuses("post") is False
        assert instance._refuses("put") is True

    def test_a_decorated_action_serving_one_is_not_refused(self) -> None:
        class _ViewSet(ServiceViewSet):
            @service_action(_action(), methods=["post"])
            def run(self, request: Any) -> None:
                """Stubbed."""

        instance = _ViewSet()
        instance.action_map = {"post": "run"}
        assert instance._refuses_without_a_spec("post") is False


class TestKernelSpecsServed:
    def test_kernel_specs_served_leaves_it_unresolved(self) -> None:
        action = _action()
        instance = _viewset(action)()
        instance.action_map = {"post": "create"}
        assert instance._kernel_specs_served() == {"POST": action}
        assert instance._kernel_specs_served()["POST"] is action

    def test_it_is_read_off_a_decorated_handler_too(self) -> None:
        action = _action()

        class _ViewSet(ServiceViewSet):
            @service_action(action, methods=["post"])
            def run(self, request: Any) -> None:
                """Stubbed."""

        instance = _ViewSet()
        instance.action_map = {"post": "run"}
        assert instance._kernel_specs_served()["POST"] is action


class TestResolveActionServiceSpec:
    def test_resolve_action_service_spec_leaves_it_unresolved(self) -> None:
        action = _action()
        assert resolve_action_service_spec({"create": action}, "create", "POST") is action

    def test_a_patch_falls_back_to_the_update_entry_unresolved(self) -> None:
        action = _action()
        resolved = resolve_action_service_spec({"update": action}, "partial_update", "PATCH")
        assert resolved is action


class TestGetSerializerClass:
    """The browsable form: the view's ``serializer_class``, else the first variant's."""

    @staticmethod
    def _field_names(view_set: Any, action: str = "create") -> set[str]:
        instance = view_set()
        instance.action = action
        instance.request = None
        return set(instance.get_serializer_class()().fields)

    def test_the_first_variant_s_body_where_the_view_sets_none(self) -> None:
        assert self._field_names(_viewset(_action())) == {"alpha"}

    def test_the_view_s_own_serializer_class_outranks_it(self) -> None:
        viewset = _viewset(_action(), serializer_class=_BIn)
        assert self._field_names(viewset) == {"beta"}

    def test_a_decorated_action_answers_the_same(self) -> None:
        class _ViewSet(ActionSerializerResolver, GenericViewSet):
            @service_action(_action(), methods=["post"])
            def run(self, request: Any) -> None:
                """Stubbed."""

        assert self._field_names(_ViewSet, "run") == {"alpha"}

    def test_a_page_rendered_as_html_answers(self, settings: Any) -> None:
        settings.TEMPLATES = [
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": True,
                "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
            }
        ]
        attrs = {"renderer_classes": [BrowsableAPIRenderer, JSONRenderer]}
        view = _viewset(_action(), **attrs).as_view({"post": "create"})
        answer = view(factory.options("/", HTTP_ACCEPT="text/html"))
        answer.render()
        assert answer.status_code == 200
        assert 'name="alpha"' in answer.content.decode()


def _members(answer: Any, method: str = "POST") -> list[dict[str, Any]]:
    return answer.data["actions"][method]["anyOf"]


def _keys(member: dict[str, Any]) -> set[str]:
    return set(member["properties"])


class TestOptions:
    def test_each_variant_is_a_member_of_any_of(self) -> None:
        answer = _options(_viewset(_action()).as_view({"post": "create"}))
        assert [_keys(member) for member in _members(answer)] == [{"alpha"}, {"beta"}]
        assert set(answer.data["actions"]) == {"POST"}

    def test_each_member_is_what_the_plain_spec_would_describe(self) -> None:
        plain = _viewset(_spec_a()).as_view({"post": "create"})
        discriminated = _viewset(_action(a=_spec_a(), b=_spec_b())).as_view({"post": "create"})
        assert _members(_options(discriminated))[0] == _options(plain).data["actions"]["POST"]

    def test_a_variant_the_caller_may_not_send_adds_no_member(self) -> None:
        action = _action(a=_spec_a((_Allow("editor"),)), b=_spec_b())
        view = _viewset(action).as_view({"post": "create"})
        assert [_keys(member) for member in _members(_options(view, "ada"))] == [{"beta"}]

    def test_every_variant_refusing_leaves_the_method_out(self) -> None:
        action = _action(a=_spec_a((_Allow(),)), b=_spec_b((_Allow(),)))
        view = _viewset(action).as_view({"post": "create"})
        assert "POST" not in _options(view).data.get("actions", {})

    def test_a_variant_with_no_body_adds_no_member(self) -> None:
        action = _action(a=_spec_a(), none=_bodyless())
        view = _viewset(action).as_view({"post": "create"})
        assert [_keys(member) for member in _members(_options(view))] == [{"alpha"}]

    def test_every_variant_with_no_body_is_described_as_a_plain_body_less_spec_is(self) -> None:
        """Never an empty ``anyOf``, and the method stays described: its write is not refused."""
        plain = _viewset(_bodyless()).as_view({"post": "create"})
        action = _action(one=_bodyless(), two=_bodyless())
        view = _viewset(action).as_view({"post": "create"})
        described = _options(view).data["actions"]["POST"]
        assert "anyOf" not in described
        assert described == _options(plain).data["actions"]["POST"]

    def test_a_variant_that_cannot_be_described_adds_no_member(self) -> None:
        class _NeedsTheCall(serializers.Serializer):
            def get_fields(self) -> dict[str, Any]:
                return {self.context["tenant"]: serializers.CharField()}

        needs = ServiceSpec(
            service=lambda *, data: None,
            permissions=_OPEN,
            validator=SerializerValidator(_NeedsTheCall),
        )
        view = _viewset(_action(needs=needs, a=_spec_a())).as_view({"post": "create"})
        assert [_keys(member) for member in _members(_options(view))] == [{"alpha"}]

    def test_a_put_is_described_less_each_variant_s_own_target_reads(self) -> None:
        def variant(*names: str) -> ServiceSpec:
            return ServiceSpec(
                service=lambda *, instance, data: None,
                permissions=_OPEN,
                validator=SerializerValidator(_AIn),
                instance_selector_spec=SelectorSpec(
                    kind=SelectorKind.RETRIEVE,
                    selector=lambda **kwargs: None,
                    reads=Parameters.of(*(Parameter(name, "integer") for name in names)),
                ),
            )

        action = _action(one=variant("pk"), two=variant("pk", "tenant"))
        view = _viewset(action, key="update").as_view({"put": "update"})
        members = _members(_options(view, pk=1), "PUT")
        # Neither variant's reads are in the body, so the two are one body and one member.
        assert [_keys(member) for member in members] == [{"alpha"}]

    def test_a_patch_action_is_never_described(self) -> None:
        row = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda **kwargs: None,
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
        )
        variant = ServiceSpec(
            service=lambda *, instance: None, permissions=_OPEN, instance_selector_spec=row
        )
        view = _viewset(_action(a=variant), key="partial_update").as_view(
            {"patch": "partial_update"}
        )
        answer = _options(view, pk=1)
        assert "actions" not in answer.data or answer.data["actions"] == {}
        assert "PATCH" in answer["Allow"]


CASES = {
    # (each variant's check, who signs in, the key chosen, the members OPTIONS shows)
    "both admit": (lambda: (_OPEN, _OPEN), "ada", "a", [{"alpha"}, {"beta"}]),
    "the first refuses": (lambda: ((_Allow(),), _OPEN), "ada", "b", [{"beta"}]),
    "the second refuses": (lambda: (_OPEN, (_Allow(),)), "ada", "a", [{"alpha"}]),
    "both refuse": (lambda: ((_Allow(),), (_Allow(),)), "ada", "a", []),
    "both refuse an anonymous caller": (lambda: ((_Allow(),), (_Allow(),)), None, "a", []),
    "a check that reads the arguments admits": (
        lambda: ((_OwnerOnly(),), (_Allow(),)),
        "ada",
        "a",
        [{"alpha"}],
    ),
}


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("body", [b"{}", b"{"], ids=["incomplete", "unparseable"])
def test_options_shows_exactly_the_variants_whose_write_is_not_refused_first(
    case: str, body: bytes
) -> None:
    """A caller shown no variant is refused whatever it sends; one shown any is told its 400."""
    checks, username, chosen, shown = CASES[case]
    first, second = checks()
    user = None if username is None else User.objects.create(username=username)
    action = DiscriminatedAction(
        lambda *, data: chosen, {"a": _spec_a(first), "b": _spec_b(second)}
    )
    view = _viewset(
        action, authentication_classes=[SessionAuthentication], permission_classes=[]
    ).as_view({"post": "create"})

    options = factory.options("/")
    posted = factory.post("/", body, content_type="application/json")
    if user is not None:
        force_authenticate(options, user)
        force_authenticate(posted, user)

    answer = view(options)
    assert answer.status_code == 200
    actions = answer.data.get("actions", {})
    assert [_keys(member) for member in actions.get("POST", {}).get("anyOf", [])] == shown
    assert ("POST" in actions) is bool(shown)
    assert view(posted).status_code == (400 if shown else 403)


def test_a_method_only_a_discriminated_action_serves_answers_from_the_specs_not_drf() -> None:
    """No ``serializer_class`` or ``get_object``: DRF's metadata would raise probing them."""
    view = _viewset(_action()).as_view({"post": "create"})
    assert _options(view).status_code == 200
