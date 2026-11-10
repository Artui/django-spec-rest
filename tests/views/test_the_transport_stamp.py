from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django_service_specs import (
    TRANSPORT_KEY,
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
    call_transport,
)
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.present import present
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from django_spec_rest import (
    REST_TRANSPORT,
    DiscriminatedAction,
    SelectorRetrieveView,
    ServiceCreateView,
    ServiceViewSet,
    build_offline_context,
)
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.views.utils import view_call_context

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _ReadingIn(serializers.Serializer):
    name = serializers.CharField()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        self.context["seen"]["input serializer"] = self.context.get(TRANSPORT_KEY)
        return attrs


class _ReadingOut(serializers.Serializer):
    name = serializers.CharField()
    transport = serializers.SerializerMethodField()

    def get_transport(self, value: Any) -> Any:
        return self.context.get(TRANSPORT_KEY)


class _ReadingCheck(PermissionCheck):
    def __init__(self, seen: dict[str, Any]) -> None:
        self.seen = seen

    def has_permission(self, principal: Any, spec: Any, *, call_context: Any) -> bool:
        self.seen["check"] = call_transport(call_context)
        return True


def _reader(seen: dict[str, Any], stage: str, answer: Any) -> Any:
    def read(*, call_context: dict[str, Any]) -> Any:
        seen[stage] = call_transport(call_context)
        return answer

    return read


def _reading_spec(seen: dict[str, Any]) -> ServiceSpec:
    def service(*, data: Any, call_context: dict[str, Any]) -> SimpleNamespace:
        seen["service"] = call_transport(call_context)
        call_context["seen"] = seen
        return SimpleNamespace(name=data["name"])

    return ServiceSpec(
        service=service,
        permissions=(_ReadingCheck(seen),),
        kwargs=_reader(seen, "kwargs", {}),
        input_data=_reader(seen, "input_data", {"name": "Ada"}),
        validator=SerializerValidator(
            _ReadingIn, serializer_context=_reader(seen, "validator", {"seen": seen})
        ),
        presenter=SerializerPresenter(
            _ReadingOut, serializer_context=_reader(seen, "presenter", {})
        ),
    )


class TestOnAView:
    def test_the_value_is_the_package_s_own_plain_string(self) -> None:
        assert REST_TRANSPORT == "rest"
        assert type(REST_TRANSPORT) is str

    def test_every_stage_of_a_write_reads_one_value(self) -> None:
        seen: dict[str, Any] = {}

        class _View(ServiceCreateView):
            spec = _reading_spec(seen)

        response = _View.as_view()(factory.post("/", {"name": "Ada"}, format="json"))

        assert response.status_code == 201
        assert response.data == {"name": "Ada", "transport": "rest"}
        assert seen == dict.fromkeys(
            ("check", "kwargs", "input_data", "validator", "input serializer", "service"), "rest"
        ) | {"presenter": "rest"}

    def test_a_selector_reads_it(self) -> None:
        seen: dict[str, Any] = {}

        def one(*, pk: int, call_context: dict[str, Any]) -> SimpleNamespace:
            seen["selector"] = call_transport(call_context)
            return SimpleNamespace(name=str(pk))

        class _View(SelectorRetrieveView):
            serializer_class = _ReadingOut
            spec = SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=one,
                reads=Parameters.of(Parameter("pk", "integer", required=True)),
                permissions=_OPEN,
                presenter=SerializerPresenter(_ReadingOut),
            )

        response = _View.as_view()(factory.get("/"), pk="7")

        assert response.status_code == 200
        assert seen == {"selector": "rest"}
        assert response.data["transport"] == "rest"

    def test_an_options_answer_asks_its_checks_under_it(self) -> None:
        seen: dict[str, Any] = {}

        class _View(ServiceCreateView):
            spec = ServiceSpec(
                service=lambda **_: None,
                permissions=(_ReadingCheck(seen),),
                validator=SerializerValidator(_ReadingIn),
                allow_none=True,
            )

        assert _View.as_view()(factory.options("/")).status_code == 200
        assert seen == {"check": "rest"}

    def test_a_discriminator_reads_it(self) -> None:
        seen: dict[str, Any] = {}

        def choose(*, call_context: dict[str, Any]) -> str:
            seen["discriminator"] = call_transport(call_context)
            return "a"

        class _ViewSet(ServiceViewSet):
            action_specs = {
                "create": DiscriminatedAction(
                    choose,
                    {
                        "a": ServiceSpec(
                            service=lambda **_: None, permissions=_OPEN, allow_none=True
                        )
                    },
                )
            }

        view = _ViewSet.as_view({"post": "create"})

        assert view(factory.post("/", {}, format="json")).status_code == 204
        assert seen == {"discriminator": "rest"}

    def test_a_serializer_keeps_the_real_request_view_format_and_action(self) -> None:
        """The builder leaves a standard key present as ``None`` where nothing gave one."""
        contexts: list[dict[str, Any]] = []

        class _In(serializers.Serializer):
            name = serializers.CharField()

            def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
                contexts.append(self.context)
                return attrs

        class _ViewSet(ServiceViewSet):
            action_specs = {
                "create": ServiceSpec(
                    service=lambda **_: None,
                    permissions=_OPEN,
                    validator=SerializerValidator(_In),
                    allow_none=True,
                )
            }

        view = _ViewSet.as_view({"post": "create"})

        response = view(factory.post("/", {"name": "Ada"}, format="json"), format="json")

        assert response.status_code == 204
        (context,) = contexts
        assert isinstance(context["request"], Request)
        assert isinstance(context["view"], _ViewSet)
        assert context["view"].request is context["request"]
        assert context["format"] == "json"
        assert context["action"] == "create"
        assert context[TRANSPORT_KEY] == "rest"

    def test_a_view_with_no_action_has_none_there(self) -> None:
        class _View:
            pass

        context = view_call_context(_View(), Request(factory.get("/")))

        assert context["action"] is None
        assert context["format"] is None
        assert context[TRANSPORT_KEY] == "rest"


def _offline_context(**stamp: str) -> dict[str, Any]:
    offline = build_offline_context(AnonymousUser())
    return {"request": offline.request, "view": offline.view, **stamp}


def _spec_under_test(seen: dict[str, Any]) -> ServiceSpec:
    return ServiceSpec(
        service=lambda *, data: SimpleNamespace(name=data["name"]),
        permissions=_OPEN,
        validator=SerializerValidator(_ReadingIn, serializer_context=lambda: {"seen": seen}),
        presenter=SerializerPresenter(_ReadingOut),
    )


class TestUnderAnotherTransport:
    @pytest.mark.parametrize("stamp", ["mcp", "agent", "cli"])
    def test_its_stamp_is_left_alone(self, stamp: str) -> None:
        seen: dict[str, Any] = {}
        spec = _spec_under_test(seen)
        call_context = _offline_context(**{TRANSPORT_KEY: stamp})

        result = dispatch(
            spec, principal=AnonymousUser(), arguments={"name": "Ada"}, call_context=call_context
        )
        presented = present(spec, result)

        assert seen == {"input serializer": stamp}
        assert presented == {"name": "Ada", "transport": stamp}
        assert call_context[TRANSPORT_KEY] == stamp

    def test_a_live_view_handed_in_is_not_asked_for_a_dict_of_its_own(self) -> None:
        """Its ``view_call_context`` is what would stamp ``rest``, and nothing here calls it."""
        seen: dict[str, Any] = {}
        spec = _spec_under_test(seen)

        class _View(ServiceCreateView):
            pass

        view = _View()
        request = Request(factory.post("/"))
        view.request = request
        view.format_kwarg = None
        call_context = {"request": request, "view": view, TRANSPORT_KEY: "mcp"}

        dispatch(
            spec, principal=AnonymousUser(), arguments={"name": "Ada"}, call_context=call_context
        )

        assert seen == {"input serializer": "mcp"}
        assert call_context[TRANSPORT_KEY] == "mcp"
        assert not hasattr(view, "_call_context")

    def test_a_context_nobody_stamped_stays_unstamped(self) -> None:
        """``build_offline_context`` hands a pair, not a context: its caller writes the dict."""
        seen: dict[str, Any] = {}
        spec = _spec_under_test(seen)
        call_context = _offline_context()

        result = dispatch(
            spec, principal=AnonymousUser(), arguments={"name": "Ada"}, call_context=call_context
        )

        assert seen == {"input serializer": None}
        assert present(spec, result) == {"name": "Ada", "transport": None}
        assert TRANSPORT_KEY not in call_context
        assert call_transport(call_context) is None
