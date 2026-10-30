"""A kernel service asking for more input is answered with its schema, as raised.

``AdditionalInputRequired`` is a 422 that carries the JSON Schema of what the client
should send next. DRF coerces every leaf of an exception's ``detail`` to an
``ErrorDetail`` string, so the schema in the detail reads ``"default": "False"``;
the schema as raised rides on the mapped exception's ``schema`` attribute and is put
back into the body the configured ``EXCEPTION_HANDLER`` built (``restore_raised_schema``).
These assert that over kernel specs served by the three mutation views, which is the
whole of the restore on the kernel route: the same handler contract, the same body.

The handler contract is what the cases hold, one conjunct each of
``restore_raised_schema``'s guard: another error naming a ``schema`` field is left
alone (the exception type), a handler answering with a ``str`` body is left alone (the
dict), a handler whose body has no ``schema`` key of its own is left alone (the key),
and a body of ``None`` or a Django response with no ``.data`` is left alone.

An update or delete view that loads its row with ``get_object()`` over a kernel
spec naming no selector is refused when the view is built, since a kernel spec's target
is its own lookup's and ``get_object()`` is never asked for one. The update and delete
cases declare ``instance_selector_spec`` instead, its ``pk`` read required, since the
kernel's ``check_seeds`` refuses an optional read over a keyword with no default.

The cases that reach the restore through ``@service_action``, a viewset's own
``handle_exception`` or ``get_exception_handler``, and the order of a viewset's bases
are the decorator's, in ``tests/viewsets/decorators/test_service_action.py``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse, JsonResponse
from django.test import override_settings
from django_service_specs import (
    AdditionalInputRequired,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    ServiceValidationError,
    Unrestricted,
)
from rest_framework.exceptions import APIException, ErrorDetail
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import exception_handler

from django_spec_rest import ServiceCreateView, ServiceDeleteView, ServiceUpdateView
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()
_OPEN = (Unrestricted(),)

_PURGE_SCHEMA: dict[str, Any] = {
    "confirmed": {"type": "boolean", "default": False},
    "batches": {"type": "integer", "minimum": 1, "maximum": 3},
    "mode": {"enum": ["soft", None]},
}


def _purge(**_: Any) -> None:
    raise AdditionalInputRequired("Confirm the purge.", schema=_PURGE_SCHEMA)


def _reject_schema_field() -> None:
    raise ServiceValidationError({"schema": ["Not a valid schema."]})


_PURGE_SPEC = ServiceSpec(service=_purge, permissions=_OPEN, atomic=False)

# A detail route's spec names the row it acts on: the kernel refuses a target for a
# spec that declares none, so the lookup is the spec's own, read from the route's ``pk``.
# The view-resolved shape (``queryset`` and ``get_object()`` over a spec with no
# selector) is refused at ``as_view()``, below.
_PURGE_ONE_SPEC = ServiceSpec(
    service=_purge,
    permissions=_OPEN,
    atomic=False,
    instance_selector_spec=SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
    ),
)


class _PurgeCreate(ServiceCreateView):
    spec = _PURGE_SPEC


class _PurgeUpdate(ServiceUpdateView):
    spec = _PURGE_ONE_SPEC


class _PurgeDelete(ServiceDeleteView):
    spec = _PURGE_ONE_SPEC


# The views that map a ``ServiceError`` on the way to a response, reached the way a
# client reaches them. A detail route needs a row to load.
_VIEWS: dict[str, tuple[type, str, bool]] = {
    "ServiceCreateView": (_PurgeCreate, "post", False),
    "ServiceUpdateView": (_PurgeUpdate, "put", True),
    "ServiceDeleteView": (_PurgeDelete, "delete", True),
}


# An update or delete view that loads the row with ``get_object()`` over a spec
# naming no selector.
class _PurgeUpdateByGetObject(ServiceUpdateView):
    queryset = Author.objects.all()
    spec = _PURGE_SPEC


class _PurgeDeleteByGetObject(ServiceDeleteView):
    queryset = Author.objects.all()
    spec = _PURGE_SPEC


def _respond(view: type, method: str, detail: bool) -> Any:
    kwargs = {"pk": Author.objects.create(name="a").pk} if detail else {}
    response = view.as_view()(getattr(_factory, method)("/", {}, format="json"), **kwargs)  # ty: ignore[unresolved-attribute]
    response.render()
    return response


def _handled_by(name: str) -> Any:
    return override_settings(
        REST_FRAMEWORK={**settings.REST_FRAMEWORK, "EXCEPTION_HANDLER": f"{__name__}.{name}"}
    )


@pytest.mark.parametrize("entry", list(_VIEWS))
def test_the_http_body_carries_the_schema_as_it_was_raised(entry: str) -> None:
    """Read off the rendered bytes, which is what a client parses: a boolean default
    arrives as ``false`` and a bound as ``3``, not as the strings DRF's detail holds."""
    response = _respond(*_VIEWS[entry])

    assert response.status_code == 422
    assert json.loads(response.content) == {"detail": "Confirm the purge.", "schema": _PURGE_SCHEMA}


@pytest.mark.parametrize(
    "view",
    [_PurgeUpdateByGetObject, _PurgeDeleteByGetObject],
    ids=["ServiceUpdateView", "ServiceDeleteView"],
)
def test_a_view_that_loads_its_row_with_get_object_is_refused_at_as_view(view: type) -> None:
    """A kernel spec's target is its own lookup's, so one naming none would run on no row, and the view is
    refused when it is built rather than answering anything."""
    with pytest.raises(ImproperlyConfigured, match="declares no target selector"):
        view.as_view()


_seen: list[Exception] = []


def _recording(exc: Exception, context: dict[str, Any]) -> Response | None:
    """DRF's own handler, keeping hold of the exception it was given."""
    _seen.append(exc)
    return exception_handler(exc, context)


@pytest.mark.parametrize("entry", list(_VIEWS))
def test_the_handler_runs_once_and_sees_drf_s_error_details(entry: str) -> None:
    """The configured handler is handed the exception with DRF's ``ErrorDetail``
    leaves, once, whichever view the error comes through."""
    _seen.clear()
    with _handled_by("_recording"):
        response = _respond(*_VIEWS[entry])

    assert json.loads(response.content)["schema"] == _PURGE_SCHEMA
    assert len(_seen) == 1
    leaf = _seen[0].detail["schema"]["confirmed"]["default"]  # ty: ignore[unresolved-attribute]
    assert isinstance(leaf, ErrorDetail)
    assert leaf == "False"


def test_the_exception_keeps_its_details_after_the_body_is_restored() -> None:
    """DRF's default handler answers with ``exc.detail`` itself, so restoring the
    schema in place would rewrite the exception too, and anything reading it after the
    response (a logger, an error tracker) would see a different shape from the one the
    handler saw."""
    _seen.clear()
    with _handled_by("_recording"):
        response = _PurgeCreate.as_view()(_factory.post("/", {}, format="json"))

    assert response.data["schema"] == _PURGE_SCHEMA
    assert _seen[0].detail["schema"]["confirmed"]["default"] == "False"  # ty: ignore[unresolved-attribute]


class _Redacting:
    """A view's own ``handle_exception``, rewriting the body it is handed."""

    def handle_exception(self, exc: Exception) -> Response:
        response = super().handle_exception(exc)  # ty: ignore[unresolved-attribute]
        response.data["schema"] = {"redacted": True}
        return response


@pytest.mark.parametrize("entry", list(_VIEWS))
def test_an_overriding_handle_exception_has_the_last_word(entry: str) -> None:
    """A subclass's ``handle_exception`` runs after the restore, so what it writes is
    what the client gets. The restore runs inside the configured handler, beneath any
    override: running it outside would put back the schema the override replaced."""
    base, method, detail = _VIEWS[entry]
    view = type(f"_Redacting{base.__name__}", (_Redacting, base), {})

    response = _respond(view, method, detail)

    assert response.status_code == 422
    assert json.loads(response.content) == {
        "detail": "Confirm the purge.",
        "schema": {"redacted": True},
    }


def _signing(exc: Exception, context: dict[str, Any]) -> Response | None:
    """DRF's handler, with a key of its own added to the body."""
    response = exception_handler(exc, context)
    assert response is not None
    response.data["handled_by"] = "the view"
    return response


class _OwnHandler:
    """A view choosing its own exception handler over ``EXCEPTION_HANDLER``."""

    def get_exception_handler(self) -> Any:
        return _signing


@pytest.mark.parametrize("entry", list(_VIEWS))
def test_a_views_own_exception_handler_still_answers(entry: str) -> None:
    """The restore asks the view for its handler rather than reading the setting, so a
    view's own ``get_exception_handler`` still chooses it, and the schema comes back as
    raised in the body that handler built."""
    base, method, detail = _VIEWS[entry]
    view = type(f"_Own{base.__name__}", (_OwnHandler, base), {})

    response = _respond(view, method, detail)

    assert response.status_code == 422
    assert json.loads(response.content) == {
        "detail": "Confirm the purge.",
        "schema": _PURGE_SCHEMA,
        "handled_by": "the view",
    }


_declined: list[Exception] = []


def _declining(exc: Exception, context: dict[str, Any]) -> Response | None:
    """A handler that answers nothing, so DRF re-raises the error."""
    _declined.append(exc)
    return None


@pytest.mark.parametrize("entry", list(_VIEWS))
def test_a_handler_declining_the_error_runs_once(entry: str) -> None:
    """A handler returning ``None`` makes DRF's ``handle_exception`` re-raise, and the
    request fails with the mapped error, having run the handler once."""
    _declined.clear()
    with _handled_by("_declining"), pytest.raises(APIException) as caught:
        _respond(*_VIEWS[entry])

    assert len(_declined) == 1
    assert caught.value.schema == _PURGE_SCHEMA  # ty: ignore[unresolved-attribute]


def _flatten(detail: Any, attr: str = "") -> Iterator[dict[str, Any]]:
    """drf-standardized-errors' walk, restated so the test takes no dependency on it:
    every leaf of ``exc.detail`` is read for its ``.code``."""
    if isinstance(detail, dict):
        for key, value in detail.items():
            yield from _flatten(value, f"{attr}.{key}" if attr else key)
    elif isinstance(detail, list):
        for index, value in enumerate(detail):
            yield from _flatten(value, f"{attr}.{index}" if attr else str(index))
    else:
        yield {"code": detail.code, "detail": str(detail), "attr": attr}


def _standardized_errors(exc: Exception, context: dict[str, Any]) -> Response | None:
    if not isinstance(exc, APIException):
        return None
    return Response(
        {"type": "client_error", "errors": list(_flatten(exc.detail))}, status=exc.status_code
    )


def _bodiless(exc: Exception, context: dict[str, Any]) -> Response | None:
    """A handler that answers with the status alone, so ``response.data`` is ``None``."""
    if not isinstance(exc, APIException):
        return None
    return Response(status=exc.status_code)


def _plain_django(exc: Exception, context: dict[str, Any]) -> HttpResponse | None:
    """A handler answering with a Django response, which carries no ``.data``."""
    if not isinstance(exc, APIException):
        return None
    return JsonResponse({"error": str(exc.detail)}, status=exc.status_code)


def _textual(exc: Exception, context: dict[str, Any]) -> Response | None:
    """A handler answering with a ``str`` body, one that happens to say "schema"."""
    if not isinstance(exc, APIException):
        return None
    return Response("A schema is required.", status=exc.status_code)


@pytest.mark.parametrize("entry", list(_VIEWS))
def test_a_handler_reading_every_leafs_code_answers_with_its_own_body(entry: str) -> None:
    """The handler sees the detail it saw before the schema was carried as raised, and
    its body is left alone because it has no ``schema`` key of its own to restore.

    With native leaves in ``exc.detail``, this walk read ``.code`` off the ``str``
    ``"boolean"`` and raised, so the ``422`` became a ``500``.
    """
    base, method, detail = _VIEWS[entry]
    with _handled_by("_standardized_errors"):
        response = _respond(base, method, detail)

    assert response.status_code == 422
    assert set(response.data) == {"type", "errors"}
    errors = response.data["errors"]
    assert errors[0] == {"code": "service_error", "detail": "Confirm the purge.", "attr": "detail"}
    assert {
        "code": "service_error",
        "detail": "False",
        "attr": "schema.confirmed.default",
    } in errors


def test_a_handler_that_answers_with_no_body_is_left_alone() -> None:
    with _handled_by("_bodiless"):
        response = _PurgeCreate.as_view()(_factory.post("/", {}, format="json"))

    assert response.status_code == 422
    assert response.data is None


def test_a_handler_answering_with_a_string_body_is_left_alone() -> None:
    """Only a dict body has a ``schema`` key to restore into. ``"schema" in`` a ``str``
    is a substring test, so a body that merely says "schema" would otherwise be spread
    as a mapping and the ``422`` become a ``TypeError``."""
    with _handled_by("_textual"):
        response = _PurgeCreate.as_view()(_factory.post("/", {}, format="json"))

    assert response.status_code == 422
    assert response.data == "A schema is required."


def test_a_handler_answering_with_a_django_response_is_left_alone() -> None:
    """``EXCEPTION_HANDLER`` may return any ``HttpResponse``; DRF serves it as it is, so
    there is no ``.data`` to read a ``schema`` key from."""
    with _handled_by("_plain_django"):
        response = _PurgeCreate.as_view()(_factory.post("/", {}, format="json"))

    assert response.status_code == 422
    assert isinstance(response, JsonResponse)
    assert set(json.loads(response.content)) == {"error"}


class _RejectView(ServiceCreateView):
    spec = ServiceSpec(service=_reject_schema_field, permissions=_OPEN, atomic=False)


def test_another_error_naming_a_schema_field_is_left_alone() -> None:
    """A ``schema`` key is restored only off the exception that carries one."""
    response = _RejectView.as_view()(_factory.post("/", {}, format="json"))

    assert response.status_code == 400
    assert response.data == {"schema": ["Not a valid schema."]}
