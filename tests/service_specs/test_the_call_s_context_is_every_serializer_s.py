"""Over HTTP, every serializer of a kernel spec's call is handed the request's one dict.

The view builds one call context per request and hands it to the kernel's
``dispatch``. The ``SerializerValidator``'s serializer and the
``SerializerPresenter``'s are built with that very object as their ``context``,
not a copy, so a key the input serializer's ``validate()`` writes is there for
the service and for the output serializer, as one serializer validating and
rendering in a stock ``ModelViewSet`` already sees it. drfs handed each
serializer its own copy; its tests of that stay with the drfs path.

Off a request - a kernel ``dispatch`` with no request in its context, or with
the Django request a run arrived on - the serializers are built over the
offline pair as before, and nothing of that pair is written into the
transport's dict, where kernel-native code learns from ``request`` whether the
call came from one.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django_service_specs import ServiceSpec, Unrestricted
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.present import present
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _CreateView(ServiceCreateView):
    """A create view over a kernel spec, its own permission classes answering for it.

    ``MutationFlowMixin.get_permissions`` reads a drfs spec's
    ``permission_classes``, which a kernel spec has no attribute for.
    """

    def get_permissions(self) -> list[Any]:
        return [permission() for permission in self.permission_classes]


def _post(spec: ServiceSpec, body: Any, base: type[_CreateView] = _CreateView) -> Response:
    view = type("_View", (base,), {"spec": spec}).as_view()
    return view(factory.post("/", body, format="json"))


class _Seen:
    """What each stage of one call saw, by stage."""

    def __init__(self) -> None:
        self.contexts: dict[str, Any] = {}
        self.values: dict[str, Any] = {}


def _spec(seen: _Seen, **validator_kwargs: Any) -> ServiceSpec:
    class _Input(serializers.Serializer):
        name = serializers.CharField()

        def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
            seen.contexts["input"] = self.context
            self.context["note"] = "written by validate()"
            return attrs

    class _Output(serializers.Serializer):
        name = serializers.CharField()

        def to_representation(self, instance: Any) -> dict[str, Any]:
            seen.contexts["output"] = self.context
            seen.values["output"] = self.context.get("note")
            return super().to_representation(instance)

    def service(*, data: dict[str, Any], call_context: dict[str, Any]) -> dict[str, Any]:
        seen.contexts["service"] = call_context
        seen.values["service"] = call_context.get("note")
        return data

    return ServiceSpec(
        service=service,
        permissions=_OPEN,
        validator=SerializerValidator(_Input, **validator_kwargs),
        presenter=SerializerPresenter(_Output),
    )


def test_a_key_validate_writes_reaches_the_service_and_the_output_serializer() -> None:
    seen = _Seen()

    response = _post(_spec(seen), {"name": "Ada"})

    assert response.status_code == 201, response.data
    assert seen.values == {
        "service": "written by validate()",
        "output": "written by validate()",
    }


def test_every_serializer_s_context_is_the_request_s_one_dict() -> None:
    seen = _Seen()

    _post(_spec(seen), {"name": "Ada"})

    call_context = seen.contexts["service"]
    assert seen.contexts["input"] is call_context
    assert seen.contexts["output"] is call_context
    assert isinstance(call_context["request"], Request)
    assert call_context["view"]._call_context is call_context


def test_the_spec_s_context_callable_writes_into_the_one_dict() -> None:
    seen = _Seen()

    _post(_spec(seen, serializer_context=lambda: {"tenant": "acme"}), {"name": "Ada"})

    assert seen.contexts["service"]["tenant"] == "acme"
    assert seen.contexts["output"] is seen.contexts["service"]


class _ExtendingView(_CreateView):
    """A view adding a key to DRF's serializer context, as a project's view does."""

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "format": "the view's", "extra": 1}


def test_a_key_the_view_s_get_serializer_context_adds_is_in_the_one_dict() -> None:
    seen = _Seen()

    _post(_spec(seen), {"name": "Ada"}, base=_ExtendingView)

    call_context = seen.contexts["service"]
    assert seen.contexts["input"] is call_context
    assert call_context["extra"] == 1
    # The view's answer goes beneath the entries the dict already holds, so
    # every stage reads one value for each of the call's own entries.
    assert call_context["format"] is None


class TestOffARequest:
    """A kernel ``dispatch`` with no DRF request in its context leaves the transport's dict as it was."""

    def _dispatch(self, call_context: dict[str, Any]) -> _Seen:
        seen = _Seen()
        spec = _spec(seen)
        result = dispatch(
            spec, principal=AnonymousUser(), arguments={"name": "Ada"}, call_context=call_context
        )
        present(spec, result)
        return seen

    def test_no_request_stays_none_and_each_serializer_has_its_own_context(self) -> None:
        call_context: dict[str, Any] = {"request": None, "view": None}

        seen = self._dispatch(call_context)

        assert call_context["request"] is None
        assert call_context["view"] is None
        assert seen.contexts["input"] is not call_context
        assert isinstance(seen.contexts["input"]["request"], Request)
        # The service still shares the dict with every other stage.
        assert seen.contexts["service"] is call_context
        assert seen.values == {"service": None, "output": None}

    def test_a_carried_django_request_stays_the_transport_s(self) -> None:
        arrived = RequestFactory().post("/chat/")
        call_context: dict[str, Any] = {"request": arrived, "view": None}

        seen = self._dispatch(call_context)

        assert call_context["request"] is arrived
        assert call_context["view"] is None
        assert seen.contexts["input"] is not call_context
        assert seen.contexts["input"]["request"] is not arrived
