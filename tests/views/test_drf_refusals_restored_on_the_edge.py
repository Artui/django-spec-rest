"""Over the kernel route, an author's DRF refusal leaves exactly as it was raised.

An author applies ``translating_drf_refusals`` to a callable of a kernel spec,
or asks a DRF permission class through ``DRFPermissionCheck``, so the kernel's
``dispatch`` reads the refusal as its own. The edge restores the exception the
author raised before DRF's handler reads it, so every route that answered the
exception answers it as before: the status and body of a live view, byte for
byte, and the class, detail and status a caller of the edge catches.

The class checks are what fail with the restore removed; a ``403`` body would
match without it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django_service_specs import (
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from django_service_specs.authorization.not_permitted import NotPermitted as KernelNotPermitted
from rest_framework.authentication import BasicAuthentication
from rest_framework.exceptions import NotAuthenticated, PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorListView, SelectorRetrieveView, ServiceCreateView
from django_spec_rest.dispatch.kernel_edge import adispatch_kernel_spec, dispatch_kernel_spec
from django_spec_rest.service_specs.drf_not_permitted import DRFNotPermitted
from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from django_spec_rest.service_specs.translating_drf_refusals import translating_drf_refusals
from tests.service_specs.test_drf_refusals_on_the_kernel_route import (
    _SERVICE_SEATS,
    _araising,
    _raising,
    _selector_spec,
    _service_spec,
)
from tests.testapp.models import Post
from tests.views.test_kernel_edge import CORES, _parts

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()
_OPEN = (Unrestricted(),)

# A `_service_spec` seat the author decorates, and a `_selector_spec` one.
_SEATS = pytest.mark.parametrize(
    "seat",
    [*_SERVICE_SEATS, "selector", "selector_precondition", "selector_kwargs", "extend_queryset"],
)


def _spec(seat: str, error: Exception) -> Any:
    build = _service_spec if seat in _SERVICE_SEATS else _selector_spec
    return build(seat, _raising(error), translating_drf_refusals)


@CORES
@_SEATS
@pytest.mark.parametrize(
    "error",
    [
        ValidationError({"title": ["Too long."]}),
        PermissionDenied("Archived posts are read-only."),
        NotAuthenticated(),
    ],
    ids=["validation-error", "permission-denied", "not-authenticated"],
)
def test_a_refusal_is_the_exception_the_author_raised(
    core: Callable[..., Any], seat: str, error: Exception
) -> None:
    with pytest.raises(type(error)) as excinfo:
        core(_spec(seat, error), **_parts({}))

    assert excinfo.value is error


class _Locked(ValidationError):
    status_code = 423


@CORES
def test_a_project_subclass_with_its_own_status_is_the_exception_raised(
    core: Callable[..., Any],
) -> None:
    error = _Locked("locked")

    with pytest.raises(_Locked) as excinfo:
        core(
            ServiceSpec(permissions=_OPEN, service=translating_drf_refusals(_raising(error))),
            **_parts({}),
        )

    assert excinfo.value is error
    assert excinfo.value.status_code == 423


@CORES
def test_the_exception_keeps_the_context_it_was_raised_in(core: Callable[..., Any]) -> None:
    def service(**_: Any) -> None:
        try:
            {}["missing"]
        except KeyError:
            raise ValidationError("whole") from None

    with pytest.raises(ValidationError) as excinfo:
        core(
            ServiceSpec(permissions=_OPEN, service=translating_drf_refusals(service)), **_parts({})
        )

    assert isinstance(excinfo.value.__context__, KeyError)
    assert excinfo.value.__suppress_context__ is True


@CORES
def test_a_raise_with_no_context_is_restored_with_none(core: Callable[..., Any]) -> None:
    with pytest.raises(PermissionDenied) as excinfo:
        core(
            ServiceSpec(
                permissions=_OPEN,
                service=translating_drf_refusals(_raising(PermissionDenied("nope"))),
            ),
            **_parts({}),
        )

    assert excinfo.value.__context__ is None


@CORES
def test_the_exception_keeps_the_cause_it_was_raised_from(core: Callable[..., Any]) -> None:
    """``from original`` sets the cause and suppresses the context, as it did on the drfs path."""
    original = KeyError("original")

    def service(**_: Any) -> None:
        raise ValidationError("whole") from original

    with pytest.raises(ValidationError) as excinfo:
        core(
            ServiceSpec(permissions=_OPEN, service=translating_drf_refusals(service)), **_parts({})
        )

    assert excinfo.value.__cause__ is original
    assert excinfo.value.__suppress_context__ is True


@CORES
def test_a_refusal_raised_from_another_is_restored_from_the_marker_not_the_cause(
    core: Callable[..., Any],
) -> None:
    """The package's own ``DRFNotPermitted`` is left as raised, so it carries no marker to restore.

    Its cause is a DRF ``PermissionDenied``, which a restore that read the
    exception's cause rather than the marker would raise in its place.
    """
    error = DRFNotPermitted("x")

    def service(**_: Any) -> None:
        raise error from PermissionDenied("y")

    with pytest.raises(DRFNotPermitted) as excinfo:
        core(
            ServiceSpec(permissions=_OPEN, service=translating_drf_refusals(service)), **_parts({})
        )

    assert excinfo.value is error


@CORES
def test_the_kernel_s_denial_still_leaves_as_the_package_s_not_permitted(
    core: Callable[..., Any],
) -> None:
    """Answered by the map, which the restore leaves alone."""
    with pytest.raises(DRFNotPermitted) as excinfo:
        core(
            ServiceSpec(permissions=_OPEN, service=_raising(KernelNotPermitted("kernel's"))),
            **_parts({}),
        )

    assert type(excinfo.value) is DRFNotPermitted
    assert str(excinfo.value.detail) == "kernel's"


@CORES
def test_an_async_service_s_refusal_is_restored_too(core: Callable[..., Any]) -> None:
    error = PermissionDenied("nope")

    with pytest.raises(PermissionDenied) as excinfo:
        core(
            ServiceSpec(permissions=_OPEN, service=translating_drf_refusals(_araising(error))),
            **_parts({}),
        )

    assert excinfo.value is error


def test_the_async_edge_restores_as_the_sync_edge_does() -> None:
    error = PermissionDenied("nope")
    spec = ServiceSpec(permissions=_OPEN, service=translating_drf_refusals(_raising(error)))

    with pytest.raises(PermissionDenied) as excinfo:
        async_to_sync(adispatch_kernel_spec)(spec, **_parts({}))

    assert excinfo.value is error
    with pytest.raises(PermissionDenied) as sync_excinfo:
        dispatch_kernel_spec(spec, **_parts({}))
    assert sync_excinfo.value is error


class _Unauthenticated(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        raise NotAuthenticated()


class _Refusing(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        raise PermissionDenied("nope")


@CORES
@pytest.mark.parametrize(
    ("permission", "error"),
    [(_Unauthenticated, NotAuthenticated), (_Refusing, PermissionDenied)],
    ids=["not-authenticated", "permission-denied"],
)
def test_a_permission_class_s_raised_refusal_is_the_class_that_was_raised(
    core: Callable[..., Any], permission: type[BasePermission], error: type[Exception]
) -> None:
    spec = ServiceSpec(permissions=(DRFPermissionCheck([permission]),), service=lambda: None)

    with pytest.raises(error) as excinfo:
        core(spec, **_parts({}))

    assert type(excinfo.value) is error


# --- Over HTTP, as the drfs path answered ------------------------------------


def _served(view: Any, method: str = "post", data: Any = None) -> Any:
    request = getattr(_factory, method)("/", data if data is not None else {}, format="json")
    response = view(request)
    response.render()
    return response


def _create(error: Exception, seat: str = "service", *, authenticated: bool = False) -> Any:
    class _View(ServiceCreateView):
        permission_classes: Any = []
        authentication_classes: Any = [BasicAuthentication] if authenticated else []
        spec = _spec(seat, error)

        def get_permissions(self) -> list[Any]:
            return []

    return _View.as_view()


_SERVICE_HTTP_SEATS = pytest.mark.parametrize("seat", ["service", "precondition", "kwargs"])


@pytest.mark.parametrize(
    ("error", "status", "body"),
    [
        (ValidationError("whole"), 400, b'["whole"]'),
        (ValidationError({"title": ["bad"]}), 400, b'{"title":["bad"]}'),
        (PermissionDenied("nope"), 403, b'{"detail":"nope"}'),
        (_Locked("locked"), 423, b'["locked"]'),
    ],
    ids=["message", "mapping", "permission-denied", "project-subclass"],
)
@_SERVICE_HTTP_SEATS
def test_a_service_spec_s_refusal_answers_as_the_drfs_path_did(
    error: Exception, status: int, body: bytes, seat: str
) -> None:
    response = _served(_create(error, seat))

    assert (response.status_code, response.content) == (status, body)


@_SERVICE_HTTP_SEATS
def test_not_authenticated_answers_401_with_its_challenge(seat: str) -> None:
    response = _served(_create(NotAuthenticated(), seat, authenticated=True))

    assert response.status_code == 401
    assert response.content == b'{"detail":"Authentication credentials were not provided."}'
    assert response["WWW-Authenticate"] == 'Basic realm="api"'


@pytest.mark.parametrize(
    ("error", "status", "body"),
    [
        (ValidationError("whole"), 400, b'["whole"]'),
        (ValidationError({"title": ["bad"]}), 400, b'{"title":["bad"]}'),
        (PermissionDenied("nope"), 403, b'{"detail":"nope"}'),
    ],
    ids=["message", "mapping", "permission-denied"],
)
@pytest.mark.parametrize("seat", ["selector", "selector_precondition", "selector_kwargs"])
def test_a_selector_list_view_s_refusal_answers_as_the_drfs_path_did(
    error: Exception, status: int, body: bytes, seat: str
) -> None:
    class _View(SelectorListView):
        spec = _spec(seat, error)

        def get_permissions(self) -> list[Any]:
            return []

    response = _served(_View.as_view(), "get")

    assert (response.status_code, response.content) == (status, body)


@pytest.mark.parametrize(
    ("permission", "status", "body", "challenge"),
    [
        (
            _Unauthenticated,
            401,
            b'{"detail":"Authentication credentials were not provided."}',
            'Basic realm="api"',
        ),
        (_Refusing, 403, b'{"detail":"nope"}', None),
    ],
    ids=["not-authenticated", "permission-denied"],
)
def test_a_permission_class_s_raised_refusal_answers_as_the_drfs_path_did(
    permission: type[BasePermission], status: int, body: bytes, challenge: str | None
) -> None:
    post = Post.objects.create(title="t")

    class _View(SelectorRetrieveView):
        authentication_classes: Any = [BasicAuthentication]
        spec = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda: Post.objects.get(pk=post.pk),
            permissions=(DRFPermissionCheck([permission]),),
        )

        def get_permissions(self) -> list[Any]:
            return []

    response = _served(_View.as_view(), "get")

    assert (response.status_code, response.content) == (status, body)
    assert response.get("WWW-Authenticate") == challenge
