"""``view_call_context``: the one call-context dict of the request a view serves.

The helper's own contract, and what the kernel route hands each callable of a
kernel spec that declares ``call_context``: the view's dict, as the very
object, so a value one stage keeps there is read by the next.
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
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorRetrieveView, ServiceCreateView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.views.utils import view_call_context
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _View:
    action = "create"

    def get_serializer_context(self) -> dict[str, Any]:
        return {}


def _request() -> Request:
    return Request(factory.get("/"))


def test_the_dict_carries_the_edge_s_four_standard_entries() -> None:
    view, request = _View(), _request()
    assert view_call_context(view, request) == {
        "request": request,
        "view": view,
        "format": None,
        "action": "create",
    }


def test_a_view_with_no_action_is_a_call_with_none() -> None:
    view = _View()
    view.action = ""
    assert view_call_context(view, _request())["action"] is None


def test_one_view_is_one_dict_and_another_view_another() -> None:
    view, request = _View(), _request()
    assert view_call_context(view, request) is view_call_context(view, request)
    assert view_call_context(_View(), request) is not view_call_context(view, request)


class _NameIn(serializers.Serializer):
    name = serializers.CharField()


class _KernelCreateView(ServiceCreateView):
    """``get_permissions`` answers the view's own classes, as for a spec setting none.

    ``MutationFlowMixin.get_permissions`` reads ``spec.permission_classes``,
    which a kernel spec has no attribute for.
    """

    def get_permissions(self) -> list[Any]:
        return [permission() for permission in self.permission_classes]


@pytest.mark.django_db
def test_every_callable_of_a_kernel_service_is_handed_the_view_s_dict() -> None:
    """The ``kwargs`` and ``input_data`` providers, both seats' context callables
    and the service: each declaring ``call_context`` is handed the one dict, and
    what the first keeps there the last reads."""
    seen: dict[str, Any] = {}

    def recording(stage: str, answer: Any = None) -> Any:
        def provide(*, call_context: dict[str, Any]) -> Any:
            seen[stage] = call_context
            call_context.setdefault("first", stage)
            return {} if answer is None else answer

        return provide

    def service(*, data: Any, call_context: dict[str, Any]) -> Author:
        seen["service"] = call_context
        return Author.objects.create(name=data["name"])

    class _View(_KernelCreateView):
        spec = ServiceSpec(
            service=service,
            permissions=_OPEN,
            kwargs=recording("kwargs"),
            input_data=recording("input_data"),
            validator=SerializerValidator(_NameIn, serializer_context=recording("validator")),
            presenter=SerializerPresenter(
                AuthorSerializer, serializer_context=recording("presenter")
            ),
        )

    response = _View.as_view()(factory.post("/", {"name": "Ada"}, format="json"))

    assert response.status_code == 201
    assert set(seen) == {"kwargs", "input_data", "validator", "presenter", "service"}
    the_dict = seen["service"]
    assert all(context is the_dict for context in seen.values())
    assert the_dict["view"]._call_context is the_dict
    assert the_dict["request"] is the_dict["view"].request
    assert the_dict["first"] in seen


@pytest.mark.django_db
def test_a_kernel_selector_is_handed_the_view_s_dict() -> None:
    seen: dict[str, Any] = {}
    author = Author.objects.create(name="Ada")

    def one(*, pk: int, call_context: dict[str, Any]) -> Author | None:
        seen["selector"] = call_context
        return Author.objects.filter(pk=pk).first()

    class _View(SelectorRetrieveView):
        serializer_class = AuthorSerializer
        spec = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=one,
            reads=Parameters.of(Parameter("pk", "integer")),
            permissions=_OPEN,
        )

    response = _View.as_view()(factory.get("/"), pk=str(author.pk))

    assert response.status_code == 200
    assert seen["selector"] is seen["selector"]["view"]._call_context
    assert seen["selector"]["action"] is None
