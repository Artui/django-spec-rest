"""A kernel selector asking for more input is answered with its schema, as raised.

A selector, a precondition or a provider may raise ``AdditionalInputRequired``,
which the edge answers as a mutation's: a 422 whose ``schema`` is the JSON Schema
of what the client should send next. DRF coerces every leaf of the error's
``detail`` to a string, so the restore (``restore_raised_schema``) puts the schema
back as raised. The standalone selector views and ``@selector_action`` on DRF's
own viewsets reached no restore and served ``"default": "False"``; each case reads
the rendered bytes, so a string leaf fails it.

The mutation side is ``tests/views/test_additional_input_required_over_http.py``.
The handler contract the restore keeps (a declining handler, a ``handle_exception``
override, the viewset's own ``get_exception_handler``) runs through both decorators
in ``tests/viewsets/decorators/test_service_action.py``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.conf import settings
from django.test import override_settings
from django_service_specs import AdditionalInputRequired, SelectorKind, SelectorSpec, Unrestricted
from rest_framework.exceptions import ErrorDetail
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import exception_handler
from rest_framework.viewsets import GenericViewSet, ViewSet

from django_spec_rest import (
    ActionSerializerResolver,
    SelectorListView,
    SelectorRetrieveView,
    SelectorViewSet,
    selector_action,
)

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"confirmed": {"type": "boolean", "default": False}, "limit": {"maximum": 3}},
}
_SENT = {"detail": "Say which.", "schema": _SCHEMA}


def _asking() -> None:
    raise AdditionalInputRequired("Say which.", schema=_SCHEMA)


def _spec(kind: SelectorKind) -> SelectorSpec:
    return SelectorSpec(kind=kind, selector=_asking, permissions=_OPEN)


def _served(view: Any) -> tuple[int, Any]:
    response = view(factory.get("/"))
    response.render()
    return response.status_code, json.loads(response.content)


@pytest.mark.parametrize(
    ("base", "kind"),
    [(SelectorListView, SelectorKind.LIST), (SelectorRetrieveView, SelectorKind.RETRIEVE)],
)
def test_a_selector_view_serves_the_schema_as_raised(base: type, kind: SelectorKind) -> None:
    view = type("_View", (base,), {"spec": _spec(kind)}).as_view()
    assert _served(view) == (422, _SENT)


# Every way a ``@selector_action`` can sit on a viewset, keyed by its bases, as
# ``@service_action``'s own cases are: DRF's own two, and this package's bases on
# either side of ``GenericViewSet``, where ``APIView.handle_exception`` shadows
# the package's restore.
_BASES: dict[str, tuple[type, ...]] = {
    "GenericViewSet": (GenericViewSet,),
    "ViewSet": (ViewSet,),
    "SelectorViewSet": (SelectorViewSet,),
    "ActionSerializerResolver, GenericViewSet": (ActionSerializerResolver, GenericViewSet),
    "GenericViewSet, ActionSerializerResolver": (GenericViewSet, ActionSerializerResolver),
}


_seen: list[Exception] = []


def _recording(exc: Exception, context: dict[str, Any]) -> Response | None:
    """DRF's own handler, keeping hold of the exception it was given."""
    _seen.append(exc)
    return exception_handler(exc, context)


@pytest.mark.parametrize("kind", [SelectorKind.LIST, SelectorKind.RETRIEVE])
@pytest.mark.parametrize("bases", list(_BASES))
def test_a_selector_action_serves_the_schema_as_raised_on_any_viewset(
    bases: str, kind: SelectorKind
) -> None:
    """The configured handler runs once and sees DRF's ``ErrorDetail`` leaves, as
    it does under ``@service_action``; the restore puts them back afterwards."""

    @selector_action(_spec(kind))
    def ask(self: Any, request: Any, *args: Any, **kwargs: Any) -> None: ...

    viewset = type("_ViewSet", _BASES[bases], {"ask": ask})
    _seen.clear()
    with override_settings(
        REST_FRAMEWORK={**settings.REST_FRAMEWORK, "EXCEPTION_HANDLER": f"{__name__}._recording"}
    ):
        assert _served(viewset.as_view({"get": "ask"})) == (422, _SENT)

    assert len(_seen) == 1
    leaf = _seen[0].detail["schema"]["properties"]["confirmed"]["default"]  # ty: ignore[unresolved-attribute]
    assert isinstance(leaf, ErrorDetail)
    assert leaf == "False"
