"""What a live view owes a kernel spec, three of them done and one still a strict xfail.

Each case is written against the public surface, a view over a kernel spec
driven through ``as_view()``. The last, a nested selector's ``permissions``
refused at ``as_view()``, is still a strict xfail naming the edge's gap.

- **A description of the input serializer is handed the call's request and
  view.** drfs described the serializer the call validates with in the call's
  own context, so a ``get_fields`` scoped by ``self.context["request"]``
  declares the fields the call validates. The kernel route describes it in
  the call's own context too, so a request-scoped serializer builds its fields
  for the caller (``test_a_request_scoped_serializer_describes_the_fields_the_call_validates``).
- **A view's ``get_*_kwargs`` hooks and its ``get_input_serializer_context``
  layer reach the call.** A hook value for a service keyword arrives at the
  service, and the view's input context layer at the input serializer
  (``test_a_service_kwargs_hook_value_reaches_the_service``,
  ``test_the_view_s_input_context_layer_reaches_the_input_serializer``).
- **A nested selector's ``permissions`` are refused at ``as_view()``.** The
  kernel asks the spec being dispatched, never the selector resolving its
  target, so checks declared there guard nothing. drfs refused a nested
  spec's ``permission_classes`` at ``as_view()`` for that reason; a kernel
  spec declaring them is accepted, and they silently refuse nothing
  (``test_enforce_permissions``'s
  ``test_a_collection_selector_s_own_classes_are_not_what_answers``).
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import SelectorKind, SelectorSpec, ServiceSpec, Unrestricted
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest import ServiceCreateView
from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from django_spec_rest.service_specs.serializer_validator import SerializerValidator

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _CreateView(ServiceCreateView):
    """A create view over a kernel spec, its own permission classes answering for it."""

    permission_classes: Any = []

    def get_permissions(self) -> list[Any]:
        return [permission() for permission in self.permission_classes]


def _post(spec: ServiceSpec, body: Any, *, user: Any = None, **attrs: Any) -> Response:
    view = type("_View", (_CreateView,), {"spec": spec, **attrs}).as_view()
    request = factory.post("/", body, format="json")
    if user is not None:
        force_authenticate(request, user=user)
    return view(request)


class _ScopedToTheCaller(serializers.Serializer):
    """A field only staff may send, decided by the request the serializer is built with."""

    name = serializers.CharField()

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        if self.context["request"].user.is_staff:
            fields["note"] = serializers.CharField()
        return fields


def test_a_request_scoped_serializer_describes_the_fields_the_call_validates() -> None:
    received: dict[str, Any] = {}
    spec = ServiceSpec(
        service=lambda *, data: received.update(data),
        permissions=_OPEN,
        validator=SerializerValidator(_ScopedToTheCaller),
    )
    staff = User.objects.create(username="staff", is_staff=True)

    response = _post(spec, {"name": "Ada", "note": "kept"}, user=staff)

    assert response.status_code == 204, response.data
    assert received == {"name": "Ada", "note": "kept"}


def _hooked(method: str, answer: dict[str, Any]) -> dict[str, Any]:
    return {method: lambda self, *args, **kwargs: dict(answer)}


def test_a_service_kwargs_hook_value_reaches_the_service() -> None:
    received: list[Any] = []
    spec = ServiceSpec(service=lambda *, tenant="none": received.append(tenant), permissions=_OPEN)

    _post(spec, {}, **_hooked("get_service_kwargs", {"tenant": "from the view"}))

    assert received == ["from the view"]


def test_the_view_s_input_context_layer_reaches_the_input_serializer() -> None:
    seen: list[Any] = []

    class _Input(serializers.Serializer):
        name = serializers.CharField()

        def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
            seen.append(self.context.get("tenant"))
            return attrs

    spec = ServiceSpec(
        service=lambda *, data: None, permissions=_OPEN, validator=SerializerValidator(_Input)
    )

    _post(spec, {"name": "Ada"}, **_hooked("get_input_serializer_context", {"tenant": "acme"}))

    assert seen == ["acme"]


class _Deny(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return False


@pytest.mark.xfail(
    strict=True,
    reason=(
        "neither as_view() nor the kernel refuses permissions on a kernel spec's "
        "collection_selector_spec, which the kernel never asks, where drfs refused a "
        "nested spec's permission_classes at as_view()"
    ),
)
def test_a_collection_selector_s_permissions_are_refused_at_as_view() -> None:
    spec = ServiceSpec(
        service=lambda *, collection: None,
        collection_selector_spec=SelectorSpec(
            kind=SelectorKind.LIST,
            selector=lambda: [],
            permissions=(DRFPermissionCheck((_Deny,)),),
        ),
        permissions=_OPEN,
    )
    view = type("_View", (_CreateView,), {"spec": spec})

    with pytest.raises(ImproperlyConfigured, match="collection_selector_spec"):
        view.as_view()
