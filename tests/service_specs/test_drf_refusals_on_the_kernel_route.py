"""On a kernel spec, an author's DRF refusal leaves as the kernel's class where the author asks.

Nothing compiles an author's callable any more, so a kernel spec's service
raising DRF's ``ValidationError`` reaches the kernel's ``dispatch`` as DRF's
class and nothing else. Two things translate it, and only those two:

- ``translating_drf_refusals``, applied by the author to a callable of the
  spec (a service, a precondition, a ``kwargs`` provider, a selector, an
  ``extend_queryset``);
- ``DRFPermissionCheck``, which asks each DRF permission class inside
  ``translate_drf_refusals``.

Each refusal DRF names is then answered as the kernel's:

- ``ValidationError`` as the kernel's ``ServiceValidationError``, with DRF's
  detail and codes, still DRF's class;
- ``PermissionDenied`` as the kernel's ``NotPermitted``, with the class's
  message and code;
- ``NotAuthenticated`` as the kernel's ``NotPermitted``, still DRF's
  ``NotAuthenticated``, so a DRF handler answering it still answers 401;
- a raise already of the kernel's class leaves exactly as raised.

Asserted against the kernel's classes and DRF's alone, so each test fails on
a tree with no translator, and the undecorated seats are held to leave DRF's
class as it was raised.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth.models import AnonymousUser
from django.db.models import QuerySet
from django_service_specs import (
    DispatchError,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from django_service_specs.authorization.not_permitted import NotPermitted as KernelNotPermitted
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.services.service_validation_error import (
    ServiceValidationError as KernelServiceValidationError,
)
from rest_framework.exceptions import (
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.permissions import BasePermission

from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from django_spec_rest.service_specs.invalid_arguments import InvalidArguments
from django_spec_rest.service_specs.not_permitted import NotPermitted
from django_spec_rest.service_specs.translating_drf_refusals import translating_drf_refusals
from tests.testapp.models import Post

pytestmark = pytest.mark.django_db

_OPEN = (Unrestricted(),)


def _run(spec: Any, arguments: dict[str, Any] | None = None) -> Any:
    return dispatch(spec, principal=AnonymousUser(), arguments=arguments or {})


def _arun(spec: Any, arguments: dict[str, Any] | None = None) -> Any:
    return async_to_sync(adispatch)(spec, principal=AnonymousUser(), arguments=arguments or {})


_ROUTES = pytest.mark.parametrize("run", [_run, _arun], ids=["sync", "async"])


def _raising(error: Exception) -> Callable[..., Any]:
    def refuse(**_: Any) -> Any:
        raise error

    return refuse


def _araising(error: Exception) -> Callable[..., Any]:
    async def refuse(**_: Any) -> Any:
        raise error

    return refuse


def _rows(**_: Any) -> QuerySet[Post]:
    return Post.objects.all()


def _extending_from(refuse: Callable[..., Any]) -> Callable[..., Any]:
    def extend(queryset: Any) -> Any:
        return refuse()

    return extend


def _service_spec(
    seat: str, refuse: Callable[..., Any], wrap: Callable[[Any], Any]
) -> ServiceSpec[Any, Any, Any]:
    """A service spec whose ``seat`` refuses through ``wrap``, every other seat passing."""
    if seat == "service":
        return ServiceSpec(permissions=_OPEN, service=wrap(refuse))
    if seat == "precondition":
        return ServiceSpec(
            permissions=_OPEN, service=lambda **_: None, preconditions=[wrap(refuse)]
        )
    if seat == "kwargs":
        return ServiceSpec(permissions=_OPEN, service=lambda **_: None, kwargs=wrap(refuse))
    if seat == "instance_lookup":
        return ServiceSpec(
            permissions=_OPEN,
            service=lambda **_: None,
            instance_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE, selector=wrap(refuse), permissions=_OPEN
            ),
        )
    if seat == "output_selector":
        return ServiceSpec(
            permissions=_OPEN,
            service=lambda **_: Post.objects.create(title="t"),
            output_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE, selector=wrap(refuse), permissions=_OPEN
            ),
        )
    assert seat == "output_extend_queryset"
    return ServiceSpec(
        permissions=_OPEN,
        service=lambda **_: Post.objects.create(title="t"),
        output_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, instance: Post.objects.filter(pk=instance.pk),
            extend_queryset=wrap(_extending_from(refuse)),
            permissions=_OPEN,
        ),
    )


def _selector_spec(
    seat: str, refuse: Callable[..., Any], wrap: Callable[[Any], Any]
) -> SelectorSpec[Any, Any]:
    if seat == "selector":
        return SelectorSpec(permissions=_OPEN, kind=SelectorKind.LIST, selector=wrap(refuse))
    if seat == "selector_precondition":
        return SelectorSpec(
            permissions=_OPEN,
            kind=SelectorKind.LIST,
            selector=_rows,
            preconditions=[wrap(refuse)],
        )
    if seat == "selector_kwargs":
        return SelectorSpec(
            permissions=_OPEN, kind=SelectorKind.LIST, selector=_rows, kwargs=wrap(refuse)
        )
    assert seat == "extend_queryset"
    return SelectorSpec(
        permissions=_OPEN,
        kind=SelectorKind.LIST,
        selector=_rows,
        extend_queryset=wrap(_extending_from(refuse)),
    )


_SERVICE_SEATS = [
    "service",
    "precondition",
    "kwargs",
    "instance_lookup",
    "output_selector",
    "output_extend_queryset",
]
_SELECTOR_SEATS = ["selector", "selector_precondition", "selector_kwargs", "extend_queryset"]
_SEATS = pytest.mark.parametrize("seat", _SERVICE_SEATS + _SELECTOR_SEATS)


def _spec(
    seat: str,
    refuse: Callable[..., Any],
    wrap: Callable[[Any], Any] = translating_drf_refusals,
) -> Any:
    build = _service_spec if seat in _SERVICE_SEATS else _selector_spec
    return build(seat, refuse, wrap)


@_ROUTES
@_SEATS
def test_a_validation_error_leaves_as_the_kernel_s_service_validation_error(
    run: Any, seat: str
) -> None:
    error = ValidationError({"title": ["Too long."]}, code="too_long")

    with pytest.raises(KernelServiceValidationError) as excinfo:
        run(_spec(seat, _raising(error)))

    refusal = excinfo.value
    # Still DRF's class, so an ``except`` written against DRF's still catches it,
    # with DRF's detail and its codes.
    assert isinstance(refusal, ValidationError)
    assert refusal.detail == {"title": ["Too long."]}
    assert refusal.get_codes() == {"title": ["too_long"]}
    assert refusal.status_code == 400
    assert refusal.__cause__ is error


@_ROUTES
def test_a_message_detail_is_kept_as_drf_gave_it(run: Any) -> None:
    with pytest.raises(KernelServiceValidationError) as excinfo:
        run(
            ServiceSpec(
                permissions=_OPEN,
                service=translating_drf_refusals(_raising(ValidationError("whole"))),
            )
        )

    assert excinfo.value.detail == ["whole"]
    assert excinfo.value.get_codes() == ["invalid"]  # ty: ignore[unresolved-attribute]


@_ROUTES
def test_an_async_service_s_refusal_is_translated_too(run: Any) -> None:
    with pytest.raises(KernelServiceValidationError):
        run(
            ServiceSpec(
                permissions=_OPEN,
                service=translating_drf_refusals(_araising(ValidationError("whole"))),
            )
        )


@_ROUTES
def test_an_async_selector_s_refusal_is_translated_too(run: Any) -> None:
    with pytest.raises(KernelNotPermitted):
        run(
            SelectorSpec(
                permissions=_OPEN,
                kind=SelectorKind.LIST,
                selector=translating_drf_refusals(_araising(PermissionDenied("nope"))),
            )
        )


@_ROUTES
@_SEATS
def test_a_permission_denied_leaves_as_the_kernel_s_not_permitted(run: Any, seat: str) -> None:
    error = PermissionDenied("Archived posts are read-only.", code="archived")

    with pytest.raises(KernelNotPermitted) as excinfo:
        run(_spec(seat, _raising(error)))

    refusal = excinfo.value
    assert refusal.message == "Archived posts are read-only."
    assert isinstance(refusal, PermissionDenied)
    assert refusal.get_codes() == "archived"
    assert refusal.status_code == 403
    assert refusal.__cause__ is error


@_ROUTES
@_SEATS
def test_not_authenticated_leaves_as_the_kernel_s_not_permitted_and_still_answers_401(
    run: Any, seat: str
) -> None:
    error = NotAuthenticated()

    with pytest.raises(KernelNotPermitted) as excinfo:
        run(_spec(seat, _raising(error)))

    refusal = excinfo.value
    assert isinstance(refusal, NotAuthenticated)
    assert refusal.message == "Authentication credentials were not provided."
    assert refusal.get_codes() == "not_authenticated"
    assert refusal.status_code == 401


class _Locked(ValidationError):
    """A project's own refusal, answered with a status of its own."""

    status_code = 423


class _Gone(PermissionDenied):
    status_code = 410


class _Expired(NotAuthenticated):
    status_code = 440
    default_detail = "Session expired."


@_ROUTES
@pytest.mark.parametrize(
    ("error", "kernel", "status", "detail"),
    [
        (_Locked("locked"), KernelServiceValidationError, 423, ["locked"]),
        (_Gone("gone"), KernelNotPermitted, 410, "gone"),
        (_Expired(), KernelNotPermitted, 440, "Session expired."),
        # A mapping a denial may carry rides across, where its message is the default.
        (PermissionDenied({"post": "Not yours."}), KernelNotPermitted, 403, {"post": "Not yours."}),
    ],
    ids=["validation", "permission", "authentication", "structured-detail"],
)
def test_a_project_subclass_keeps_its_status_and_detail(
    run: Any, error: Exception, kernel: type[Exception], status: int, detail: Any
) -> None:
    with pytest.raises(kernel) as excinfo:
        run(ServiceSpec(permissions=_OPEN, service=translating_drf_refusals(_raising(error))))

    assert excinfo.value.status_code == status  # ty: ignore[unresolved-attribute]
    assert excinfo.value.detail == detail  # ty: ignore[unresolved-attribute]
    if isinstance(error, PermissionDenied) and not isinstance(error.detail, str):
        assert excinfo.value.message == KernelNotPermitted.default_message  # ty: ignore[unresolved-attribute]


class _BothValidationErrors(KernelServiceValidationError, ValidationError):
    """DRF's ``ValidationError`` that is the kernel's service error too, as a translated one is."""

    def __init__(self, detail: Any) -> None:
        KernelServiceValidationError.__init__(self, detail)
        ValidationError.__init__(self, detail)


@_ROUTES
@pytest.mark.parametrize(
    "error",
    [
        KernelNotPermitted("kernel's own"),
        KernelServiceValidationError({"title": ["kernel's own"]}),
        # DRF's classes as well, so only the check for the kernel's keeps them.
        NotPermitted("the dual class"),
        InvalidArguments({"title": ["the dual class"]}),
        _BothValidationErrors({"title": ["a twin, translated by an inner callable"]}),
    ],
    ids=["dispatch-error", "service-error", "dual-not-permitted", "dual-invalid", "twin"],
)
def test_a_kernel_refusal_leaves_exactly_as_raised(run: Any, error: Exception) -> None:
    with pytest.raises(type(error)) as excinfo:
        run(ServiceSpec(permissions=_OPEN, service=translating_drf_refusals(_raising(error))))

    assert excinfo.value is error


@_ROUTES
@pytest.mark.parametrize(
    "error",
    [LookupError("not a refusal"), NotFound("No such post.")],
    ids=["not-drf-s", "drf-s-with-no-kernel-class"],
)
def test_any_other_exception_leaves_exactly_as_raised(run: Any, error: Exception) -> None:
    with pytest.raises(type(error)) as excinfo:
        run(ServiceSpec(permissions=_OPEN, service=translating_drf_refusals(_raising(error))))

    assert excinfo.value is error


@_ROUTES
@_SEATS
@pytest.mark.parametrize(
    "error",
    [ValidationError("whole"), PermissionDenied("nope"), NotAuthenticated()],
    ids=["validation-error", "permission-denied", "not-authenticated"],
)
def test_an_undecorated_seat_leaves_drf_s_class_as_raised(
    run: Any, seat: str, error: Exception
) -> None:
    """Nothing translates unless the author asks, so the DRF handler reads the author's own."""
    with pytest.raises(type(error)) as excinfo:
        run(_spec(seat, _raising(error), lambda fn: fn))

    assert excinfo.value is error
    assert not isinstance(error, DispatchError)


@_ROUTES
def test_a_refusal_a_generator_service_raises_while_iterated_is_drf_s_class(run: Any) -> None:
    """The service returns the generator, so the raise is after the block that translates."""
    error = PermissionDenied("not translated")

    def service(**_: Any) -> Any:
        raise error
        yield

    result = run(ServiceSpec(permissions=_OPEN, service=translating_drf_refusals(service)))

    with pytest.raises(PermissionDenied) as excinfo:
        next(result.value)

    assert excinfo.value is error


class _Refusing(BasePermission):
    raises: Exception

    def has_permission(self, request: Any, view: Any) -> bool:
        raise self.raises


class _RefusingTheRow(BasePermission):
    raises: Exception

    def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
        raise self.raises


def _guarded(permission: type[BasePermission], error: Exception) -> Any:
    refusing = type("Refusing", (permission,), {"raises": error})
    post = Post.objects.create(title="t")
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda: Post.objects.get(pk=post.pk),
        permissions=(DRFPermissionCheck([refusing]),),
    )


@_ROUTES
@pytest.mark.parametrize("permission", [_Refusing, _RefusingTheRow], ids=["class", "object"])
def test_a_permission_class_raising_permission_denied_leaves_as_not_permitted(
    run: Any, permission: type[BasePermission]
) -> None:
    error = PermissionDenied("nope", code="no_entry")

    with pytest.raises(KernelNotPermitted) as excinfo:
        run(_guarded(permission, error))

    assert excinfo.value.message == "nope"
    assert excinfo.value.get_codes() == "no_entry"  # ty: ignore[unresolved-attribute]
    assert excinfo.value.__cause__ is error


@_ROUTES
@pytest.mark.parametrize("permission", [_Refusing, _RefusingTheRow], ids=["class", "object"])
def test_a_permission_class_raising_not_authenticated_leaves_as_not_permitted(
    run: Any, permission: type[BasePermission]
) -> None:
    with pytest.raises(KernelNotPermitted) as excinfo:
        run(_guarded(permission, NotAuthenticated()))

    assert isinstance(excinfo.value, NotAuthenticated)
    assert excinfo.value.message == "Authentication credentials were not provided."
    assert excinfo.value.get_codes() == "not_authenticated"  # ty: ignore[unresolved-attribute]
    assert excinfo.value.status_code == 401  # ty: ignore[unresolved-attribute]
