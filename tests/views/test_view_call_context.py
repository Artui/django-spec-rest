"""``view_call_context``: the one call-context dict of the request a view serves.

The helper's own contract, and what the kernel route hands each callable of a
kernel spec that declares ``call_context``: the view's dict, as the very
object, so a value one stage keeps there is read by the next.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
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

from django_spec_rest import SelectorRetrieveView, ServiceCreateView, ServiceViewSet
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
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
            permissions=_OPEN,
        )

    response = _View.as_view()(factory.get("/"), pk=str(author.pk))

    assert response.status_code == 200
    assert seen["selector"] is seen["selector"]["view"]._call_context
    assert seen["selector"]["action"] is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "name", ["get_service_kwargs", "get_input_serializer_context", "get_progress_reporter"]
)
def test_a_view_hook_taking_kwargs_alone_is_never_handed_the_call_context(name: str) -> None:
    """The dict is offered by name only: a hook taking a bare ``**kwargs`` is
    handed the view and the request, as it always was."""
    seen: dict[str, Any] = {}

    def hook(self: Any, **kwargs: Any) -> dict[str, Any] | None:
        seen.update(kwargs)
        return None if name == "get_progress_reporter" else {}

    view = type(
        "_Hooked",
        (_KernelCreateView,),
        {
            "spec": ServiceSpec(
                service=lambda *, data: None,
                permissions=_OPEN,
                validator=SerializerValidator(_NameIn),
            ),
            name: hook,
        },
    )

    response = view.as_view()(factory.post("/", {"name": "Ada"}, format="json"))

    assert response.status_code == 204, response.data
    assert set(seen) == {"view", "request"}


_HOOKS = (
    "get_service_kwargs",
    "get_create_service_kwargs",
    "get_input_data",
    "get_create_input_data",
    "get_input_serializer_context",
    "get_create_input_serializer_context",
    "get_output_serializer_context",
    "get_create_output_serializer_context",
    "get_progress_reporter",
)


@pytest.mark.django_db
def test_every_viewset_hook_naming_the_call_context_is_handed_the_view_s_dict() -> None:
    """Each of a viewset's hooks, the catch-all and the per-action form alike,
    declaring ``call_context`` is handed the request's one dict."""
    seen: dict[str, Any] = {}

    def hook(name: str) -> Any:
        def answer(self: Any, *, call_context: dict[str, Any]) -> Any:
            seen[name] = call_context
            return None if name == "get_progress_reporter" else {}

        return answer

    def service(*, data: Any, call_context: dict[str, Any]) -> Author:
        seen["service"] = call_context
        return Author.objects.create(name=data["name"])

    spec = ServiceSpec(
        service=service,
        permissions=_OPEN,
        validator=SerializerValidator(_NameIn),
        presenter=SerializerPresenter(AuthorSerializer),
    )
    viewset = type(
        "_Hooked",
        (ServiceViewSet,),
        {
            "queryset": Author.objects.all(),
            "action_specs": {"create": spec},
            **{name: hook(name) for name in _HOOKS},
        },
    )

    response = viewset.as_view({"post": "create"})(
        factory.post("/", {"name": "Ada"}, format="json")
    )

    assert response.status_code == 201, response.data
    assert set(seen) == {*_HOOKS, "service"}
    assert all(context is seen["service"] for context in seen.values())


def _needs_the_call_context(*, call_context: dict[str, Any]) -> int:
    return 201


def _finalize(*, response: Any, call_context: dict[str, Any]) -> Any:
    return response


@pytest.mark.parametrize(
    "attrs",
    [{"success_status": _needs_the_call_context}, {"response_finalizer": _finalize}],
    ids=["success-status", "response-finalizer"],
)
@pytest.mark.parametrize("view", ["standalone", "viewset"])
def test_a_status_or_finalizer_naming_the_call_context_is_refused_when_the_view_is_built(
    attrs: dict[str, Any], view: str
) -> None:
    """Neither is offered the call's context, so one declaring it is refused by
    ``as_view()``: a standalone view's, and a viewset's over a kernel
    ``action_specs`` entry, which ``as_view()`` asks of each entry as the
    standalone view asks of its spec."""
    spec = ServiceSpec(
        service=lambda *, data: None,
        permissions=(Unrestricted(),),
        validator=SerializerValidator(_NameIn),
    )
    if view == "standalone":
        built = type("_View", (_KernelCreateView,), {"spec": spec, **attrs})
        with pytest.raises(ImproperlyConfigured, match="call_context"):
            built.as_view()
    else:
        built = type(
            "_ViewSet",
            (ServiceViewSet,),
            {"queryset": Author.objects.all(), "action_specs": {"create": spec}, **attrs},
        )
        with pytest.raises(ImproperlyConfigured, match="call_context"):
            built.as_view({"post": "create"})
