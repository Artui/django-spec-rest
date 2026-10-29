"""The call's context a live view hands a kernel spec: one dict per request, every stage's.

The view builds the dict on first use with DRF's four standard entries,
``request``, ``view``, ``format`` ``None`` and the view's ``action`` or
``None``, and hands that very object to the kernel's ``dispatch`` as
``call_context``. Every stage declaring ``call_context`` is handed it: the
spec's ``kwargs`` provider and ``input_data``, a target lookup, the selector,
the service, and each seat's serializer context callable. A dict the kernel is
handed reaches every stage by the kernel's own rule; these cases hold that the
view's dict is the one it is handed.
"""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorListView, ServiceCreateView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _CreateView(ServiceCreateView):
    """A create view over a kernel spec, its own permission classes answering for it."""

    def get_permissions(self) -> list[Any]:
        return [permission() for permission in self.permission_classes]


def _post(spec: ServiceSpec, body: Any, **attrs: Any) -> Response:
    view = type("_View", (_CreateView,), {"spec": spec, **attrs}).as_view()
    return view(factory.post("/", body, format="json"))


def _seen_by(seen: dict[str, Any], stage: str, answer: Any = None) -> Any:
    def stage_fn(*, call_context: dict[str, Any], **_: Any) -> Any:
        seen[stage] = call_context
        return {} if answer is None else answer

    return stage_fn


class _NameIn(serializers.Serializer):
    name = serializers.CharField()


def test_the_view_s_dict_holds_the_standard_entries_for_a_kwargs_provider() -> None:
    seen: dict[str, Any] = {}
    spec = ServiceSpec(service=lambda: None, permissions=_OPEN, kwargs=_seen_by(seen, "kwargs"))

    assert _post(spec, {}).status_code == 204

    context = seen["kwargs"]
    assert isinstance(context["request"], Request)
    assert context["view"]._call_context is context
    assert context["format"] is None
    assert context["action"] is None


def test_input_data_is_handed_the_view_s_dict() -> None:
    seen: dict[str, Any] = {}
    spec = ServiceSpec(
        service=lambda *, data: None,
        permissions=_OPEN,
        validator=SerializerValidator(_NameIn),
        input_data=_seen_by(seen, "input_data"),
        kwargs=_seen_by(seen, "kwargs"),
    )

    assert _post(spec, {"name": "Ada"}).status_code == 204

    assert seen["input_data"] is seen["kwargs"]
    assert seen["input_data"]["view"]._call_context is seen["input_data"]


@pytest.mark.parametrize(("action", "expected"), [("publish", "publish"), ("", None)])
def test_the_action_is_the_view_s_where_it_has_one(action: str, expected: str | None) -> None:
    seen: dict[str, Any] = {}
    spec = ServiceSpec(service=lambda: None, permissions=_OPEN, kwargs=_seen_by(seen, "kwargs"))

    _post(spec, {}, action=action)

    assert seen["kwargs"]["action"] == expected


def test_a_target_lookup_and_the_service_share_the_dict() -> None:
    author = Author.objects.create(name="Ada")
    seen: dict[str, Any] = {}

    def lookup(*, pk: int, call_context: dict[str, Any]) -> Author:
        seen["lookup"] = call_context
        return Author.objects.get(pk=pk)

    def service(*, instance: Author, call_context: dict[str, Any]) -> None:
        seen["service"] = call_context

    spec = ServiceSpec(
        service=service,
        permissions=_OPEN,
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lookup,
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
            permissions=_OPEN,
        ),
    )

    assert _post(spec, {"pk": author.pk}).status_code == 204

    assert seen["lookup"] is seen["service"]
    assert seen["service"]["view"]._call_context is seen["service"]


def test_a_selector_and_its_kwargs_provider_share_the_dict() -> None:
    seen: dict[str, Any] = {}

    def every(*, call_context: dict[str, Any]) -> Any:
        seen["selector"] = call_context
        return Author.objects.all()

    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=every,
        permissions=_OPEN,
        kwargs=_seen_by(seen, "kwargs"),
    )
    view = type(
        "_View", (SelectorListView,), {"spec": spec, "serializer_class": AuthorSerializer}
    ).as_view()

    assert view(factory.get("/")).status_code == 200

    assert seen["selector"] is seen["kwargs"]
    assert seen["selector"]["view"]._call_context is seen["selector"]


def test_a_many_service_s_stages_share_the_dict() -> None:
    seen: dict[str, Any] = {}

    def service(*, data: Any, call_context: dict[str, Any]) -> None:
        seen["service"] = call_context

    spec = ServiceSpec(
        service=service,
        permissions=_OPEN,
        many=True,
        validator=SerializerValidator(_NameIn),
        kwargs=_seen_by(seen, "kwargs"),
    )

    assert _post(spec, [{"name": "a"}, {"name": "b"}]).status_code == 204

    assert seen["service"] is seen["kwargs"]


def test_each_request_is_a_dict_of_its_own() -> None:
    seen: list[dict[str, Any]] = []
    spec = ServiceSpec(service=lambda *, call_context: seen.append(call_context), permissions=_OPEN)
    view = type("_View", (_CreateView,), {"spec": spec}).as_view()

    view(factory.post("/", {}, format="json"))
    view(factory.post("/", {}, format="json"))

    first, second = seen
    assert first is not second


def test_both_seats_context_callables_are_handed_the_view_s_dict() -> None:
    seen: dict[str, Any] = {}

    def service(*, data: Any, call_context: dict[str, Any]) -> Author:
        seen["service"] = call_context
        return Author.objects.create(name=data["name"])

    spec = ServiceSpec(
        service=service,
        permissions=_OPEN,
        validator=SerializerValidator(_NameIn, serializer_context=_seen_by(seen, "input")),
        presenter=SerializerPresenter(
            AuthorSerializer, serializer_context=_seen_by(seen, "output")
        ),
    )

    response = _post(spec, {"name": "Ada"})

    assert response.status_code == 201, response.data
    assert seen["input"] is seen["service"]
    assert seen["output"] is seen["service"]
