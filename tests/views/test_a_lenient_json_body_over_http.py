"""Over HTTP, the switch that lets a DRF serializer alone answer a JSON body.

A JSON body is checked against the spec's declared types before its serializer
runs, so ``{"title": 5}`` is refused for a ``CharField`` that a bare DRF
serializer takes as ``"5"``. ``lenient_json_body`` on a view, or
``SPEC_REST_LENIENT_JSON_BODY`` for a project, dispatches the lenient twin a form
body already has: each expectation is what a bare serializer answers for the same
body. The declared spec stays typed for every other transport, and off by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django_service_specs import (
    DataclassValidator,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.schema.spec_input_schema import spec_input_schema
from rest_framework import serializers
from rest_framework.routers import SimpleRouter
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import (
    DiscriminatedAction,
    ServiceCreateView,
    ServiceUpdateView,
    ServiceViewSet,
    service_action,
)
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.viewsets.service_create_mixin import ServiceCreateMixin
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_SEEN: dict[str, Any] = {}
_ON = {"SPEC_REST_LENIENT_JSON_BODY": True}
_OFF = {"SPEC_REST_LENIENT_JSON_BODY": False}


class _Nested(serializers.Serializer):
    name = serializers.CharField()


class _Input(serializers.Serializer):
    title = serializers.CharField()
    n = serializers.IntegerField(required=False)
    nested = _Nested(required=False)
    tags = serializers.ListField(child=serializers.CharField(), required=False)


def _take(*, data: Any) -> dict[str, Any]:
    _SEEN["data"] = dict(data)
    return {}


_SPEC = ServiceSpec(service=_take, validator=SerializerValidator(_Input), permissions=_OPEN)


def _call(view: Any, body: Any, **captures: Any) -> Any:
    return view(_factory.post("/", body, format="json"), **captures)


def _view(spec: ServiceSpec = _SPEC, **attrs: Any) -> Any:
    return type("_View", (ServiceCreateView,), {"spec": spec, **attrs}).as_view()


def test_off_by_default_the_kernel_answers_a_json_body() -> None:
    response = _call(_view(), {"title": 5})
    assert response.status_code == 400
    assert str(response.data["title"][0]) == "Expected a string."


def test_the_view_attribute_turns_it_on() -> None:
    assert _call(_view(lenient_json_body=True), {"title": 5}).status_code == 201
    assert _SEEN["data"] == {"title": "5"}


def test_as_view_takes_the_attribute() -> None:
    view = ServiceCreateView.as_view(spec=_SPEC, lenient_json_body=True)
    assert _call(view, {"title": 5}).status_code == 201


@override_settings(**_ON)
def test_the_setting_turns_it_on_for_a_project() -> None:
    assert _call(_view(), {"title": 5}).status_code == 201
    assert _SEEN["data"] == {"title": "5"}


@override_settings(**_ON)
def test_a_view_attribute_of_false_beats_the_setting() -> None:
    response = _call(_view(lenient_json_body=False), {"title": 5})
    assert response.status_code == 400
    assert str(response.data["title"][0]) == "Expected a string."


@override_settings(**_OFF)
def test_a_view_attribute_of_true_beats_the_setting() -> None:
    assert _call(_view(lenient_json_body=True), {"title": 5}).status_code == 201


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_a_setting_that_is_no_bool_is_refused_by_name(value: Any) -> None:
    with (
        override_settings(SPEC_REST_LENIENT_JSON_BODY=value),
        pytest.raises(ImproperlyConfigured, match="SPEC_REST_LENIENT_JSON_BODY"),
    ):
        _call(_view(), {"title": "t"})


@override_settings(SPEC_REST_LENIENT_JSON_BODY="yes")
def test_a_view_answering_for_itself_never_reads_the_setting() -> None:
    assert _call(_view(lenient_json_body=True), {"title": "t"}).status_code == 201


def test_every_refusal_is_drf_s_and_all_at_once() -> None:
    response = _call(_view(lenient_json_body=True), {"n": "x", "nested": {"name": None}})
    assert response.status_code == 400
    assert str(response.data["title"][0]) == "This field is required."
    assert str(response.data["n"][0]) == "A valid integer is required."
    assert str(response.data["nested"]["name"][0]) == "This field may not be null."


def test_a_null_is_refused_in_drf_s_words() -> None:
    response = _call(_view(lenient_json_body=True), {"title": None})
    assert str(response.data["title"][0]) == "This field may not be null."


def test_a_body_that_is_no_object_is_still_refused_at_the_edge() -> None:
    response = _call(_view(lenient_json_body=True), [{"title": "t"}])
    assert response.status_code == 400
    assert "must be an object" in str(response.data)


def test_the_kernel_s_array_cap_no_longer_judges_a_list_field() -> None:
    """What the docs warn of: a list field needs a ``max_length`` of its own under the switch."""
    body = {"title": "t", "tags": ["a", "b", "c"]}
    with override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=2):
        assert _call(_view(), body).status_code == 400
        assert _call(_view(lenient_json_body=True), body).status_code == 201


def test_a_request_with_the_switch_on_leaves_the_spec_typed() -> None:
    before = spec_input_schema(_SPEC)
    assert before["required"] == ["title"]
    assert before["properties"]["title"]["type"] == "string"
    assert before["properties"]["n"]["type"] == "integer"
    assert _call(_view(lenient_json_body=True), {"title": 5}).status_code == 201
    assert spec_input_schema(_SPEC) == before
    assert _SPEC.validator.lenient is False
    assert [param.type for param in _SPEC.parameters()][:2] == ["string", "integer"]


def test_a_call_off_http_keeps_the_kernel_s_check_with_the_switch_on() -> None:
    assert _call(_view(lenient_json_body=True), {"title": 5}).status_code == 201
    with override_settings(**_ON), pytest.raises(InvalidArguments):
        dispatch(_SPEC, principal=None, arguments={"title": 5})


@pytest.mark.parametrize("provided", [{}, {"input_data": lambda: {}}], ids=["none", "provider"])
def test_two_views_of_one_spec_each_answer_as_they_declare(provided: dict[str, Any]) -> None:
    """``[provider]`` has a twin either way, and fails with one held for both answers."""
    spec = ServiceSpec(
        service=_take, validator=SerializerValidator(_Input), permissions=_OPEN, **provided
    )
    assert _call(_view(spec, lenient_json_body=True), {"title": 5}).status_code == 201
    assert _call(_view(spec), {"title": 5}).status_code == 400
    assert _call(_view(spec, lenient_json_body=True), {"title": 5}).status_code == 201


def test_a_many_spec_s_rows_are_the_serializer_s() -> None:
    def take(*, items: list[Any]) -> list[Any]:
        _SEEN["items"] = items
        return []

    spec = ServiceSpec(
        service=take,
        validator=SerializerValidator(_Input),
        many=True,
        atomic=False,
        permissions=_OPEN,
    )
    strict = _call(_view(spec), [{"title": 5}])
    assert strict.status_code == 400
    assert _call(_view(spec, lenient_json_body=True), [{"title": 5}]).status_code == 201
    assert _SEEN["items"] == [{"title": "5"}]
    refused = _call(_view(spec, lenient_json_body=True), [{"title": "a"}, {"n": "x"}])
    assert refused.status_code == 400
    assert str(refused.data["items"][1]["title"][0]) == "This field is required."
    assert str(refused.data["items"][1]["n"][0]) == "A valid integer is required."


def _many(**fields: Any) -> ServiceSpec:
    return ServiceSpec(
        service=lambda *, items: [],
        validator=SerializerValidator(_Input),
        many=True,
        atomic=False,
        permissions=_OPEN,
        **fields,
    )


def test_a_many_spec_s_list_stays_capped() -> None:
    """A JSON list's one bound on its count: the switch relaxes each row, never the list."""
    rows = [{"title": "a"}, {"title": "b"}, {"title": "c"}]
    with override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=2):
        response = _call(_view(_many(), lenient_json_body=True), rows)
    assert response.status_code == 400
    assert "items" in response.data


def test_a_form_body_on_a_many_spec_is_refused_as_it_was() -> None:
    response = _view(_many())(_factory.post("/", {"title": "t"}, format="multipart"))
    assert response.status_code == 400
    assert {key: [str(item) for item in value] for key, value in response.data.items()} == {
        "items": ["Expected an array."]
    }


class _Actions(ServiceViewSet):
    lenient_json_body = True
    action_specs = {"create": _SPEC}  # noqa: RUF012

    @service_action(_SPEC, methods=["post"])
    def act(self, request: Any) -> None: ...


class _PerAction(ServiceViewSet):
    @service_action(_SPEC, methods=["post"], lenient_json_body=True)
    def relaxed(self, request: Any) -> None: ...

    @service_action(_SPEC, methods=["post"])
    def strict(self, request: Any) -> None: ...


class _BareViewSet(GenericViewSet):
    @service_action(_SPEC, methods=["post"])
    def act(self, request: Any) -> None: ...


class _BareDeclaring(GenericViewSet):
    lenient_json_body = True

    @service_action(_SPEC, methods=["post"])
    def act(self, request: Any) -> None: ...


def _routed(viewset: type, path: str) -> Any:
    router = SimpleRouter()
    router.register("v", viewset, basename="v")
    for pattern in router.urls:
        match = pattern.resolve(path)
        if match is not None:
            return match.func
    raise AssertionError(path)


def test_an_action_specs_entry_honours_the_viewset_s_attribute() -> None:
    assert _call(_routed(_Actions, "v/"), {"title": 5}).status_code == 201


def test_a_service_action_honours_the_viewset_s_attribute() -> None:
    assert _call(_routed(_Actions, "v/act/"), {"title": 5}).status_code in (200, 201)


def test_a_service_action_may_declare_its_own() -> None:
    assert _call(_routed(_PerAction, "v/relaxed/"), {"title": 5}).status_code in (200, 201)
    assert _call(_routed(_PerAction, "v/strict/"), {"title": 5}).status_code == 400


@override_settings(**_ON)
def test_a_mixin_on_a_generic_viewset_reads_the_setting() -> None:
    class _Mixed(ServiceCreateMixin, GenericViewSet):
        action_specs = {"create": _SPEC}  # noqa: RUF012

    assert _call(_routed(_Mixed, "v/"), {"title": 5}).status_code == 201


def test_a_service_action_on_a_bare_viewset_reads_its_own_attribute() -> None:
    assert _call(_routed(_BareViewSet, "v/act/"), {"title": 5}).status_code == 400
    assert _call(_routed(_BareDeclaring, "v/act/"), {"title": 5}).status_code in (200, 201)


@override_settings(**_ON)
def test_a_service_action_on_a_bare_viewset_reads_the_setting() -> None:
    assert _call(_routed(_BareViewSet, "v/act/"), {"title": 5}).status_code in (200, 201)


def test_a_discriminated_action_s_chosen_spec_honours_the_attribute() -> None:
    action = DiscriminatedAction(lambda: "one", {"one": _SPEC})

    class _Discriminated(ServiceViewSet):
        lenient_json_body = True
        action_specs = {"create": action}  # noqa: RUF012

    assert _call(_routed(_Discriminated, "v/"), {"title": 5}).status_code == 201


def test_a_route_capture_outranks_the_body_under_the_switch() -> None:
    """The route scopes the call, so a client's value still does not move it."""

    class _Scoped(serializers.Serializer):
        tenant = serializers.IntegerField()
        name = serializers.CharField()

    spec = ServiceSpec(service=_take, validator=SerializerValidator(_Scoped), permissions=_OPEN)
    view = _view(spec, lenient_json_body=True)
    assert _call(view, {"name": 7, "tenant": 999}, tenant="7").status_code == 201
    assert _SEEN["data"] == {"tenant": 7, "name": "7"}


def test_a_target_lookup_reads_the_route_under_the_switch() -> None:
    def rename(*, instance: Author, data: Any) -> Author:
        _SEEN["instance"] = instance
        _SEEN["data"] = dict(data)
        return instance

    class _Name(serializers.Serializer):
        name = serializers.CharField()

    spec = ServiceSpec(
        service=rename,
        validator=SerializerValidator(_Name),
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
        ),
        permissions=_OPEN,
    )
    author = Author.objects.create(name="a")
    view = ServiceUpdateView.as_view(spec=spec, lenient_json_body=True)
    request = _factory.patch("/", {"name": 7, "pk": 999999}, format="json")
    assert view(request, pk=str(author.pk)).status_code == 200
    assert _SEEN["instance"] == author
    assert _SEEN["data"] == {"name": "7"}


def test_a_dataclass_validator_is_left_its_own_check() -> None:
    @dataclass
    class _In:
        title: str

    spec = ServiceSpec(service=_take, validator=DataclassValidator(_In), permissions=_OPEN)
    assert _call(_view(spec, lenient_json_body=True), {"title": 5}).status_code == 400
