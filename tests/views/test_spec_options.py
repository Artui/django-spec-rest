"""OPTIONS on every route serving a kernel spec.

Every view and viewset base answers OPTIONS as DRF's ``APIView.options``
does, with ``name``, ``description``, ``renders``, ``parses`` and, for a
``POST`` or ``PUT`` the spec serves, ``actions``. The description is read off
the spec, never off ``serializer_class`` or a spec stage, so:

- a spec-only mutation view with no ``serializer_class`` answers, where DRF's
  metadata reached ``GenericAPIView.get_serializer_class``'s assertion;
- no selector, provider, service, precondition or affordance condition runs,
  while ``initial()`` still does (authentication and throttles);
- ``Allow`` names only the methods a spec serves;
- a method's ``actions`` entry is the JSON Schema of ``spec.parameters()``
  less what the server fills, under the edge's unknown-argument policy;
- a method is described only where the kernel's ``authorize`` grants it.

Every test drives the route through ``as_view()``, importing nothing the
description added.
"""

from __future__ import annotations

from typing import Any, TypedDict

import pytest
from django_service_specs import (
    Affordance,
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.test import APIRequestFactory
from rest_framework.throttling import BaseThrottle

from django_spec_rest import (
    SelectorListView,
    SelectorRetrieveView,
    SelectorViewSet,
    ServiceCreateView,
    ServiceDeleteView,
    ServiceUpdateView,
    ServiceViewSet,
)
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.types.service_spec import ServiceSpec as DrfsServiceSpec
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_PRESENTER = SerializerPresenter(AuthorSerializer)

# What ran, in order. Every spec stage below records itself here, and so does
# the throttle ``initial()`` asks, so one list says both that ``initial()`` ran
# and that nothing of the spec's did.
_RAN: list[str] = []


@pytest.fixture(autouse=True)
def _fresh_record() -> Any:
    _RAN.clear()
    yield
    _RAN.clear()


class _Recorded(BaseThrottle):
    def allow_request(self, request: Any, view: Any) -> bool:
        _RAN.append("throttle")
        return True


class _NameIn(serializers.Serializer):
    name = serializers.CharField(max_length=20)
    slug = serializers.CharField(max_length=20)


class _Owner(TypedDict):
    owner: str


class _Slug(TypedDict):
    slug: str


def _owner(**kwargs: Any) -> _Owner:  # pragma: no cover - a spy that must not run
    _RAN.append("kwargs provider")
    return {"owner": "server"}


def _slug(**kwargs: Any) -> _Slug:  # pragma: no cover - a spy that must not run
    _RAN.append("input_data provider")
    return {"slug": "server"}


def _precondition(**kwargs: Any) -> None:  # pragma: no cover - a spy that must not run
    _RAN.append("precondition")


def _open_now() -> bool:  # pragma: no cover - a spy that must not run
    _RAN.append("affordance condition")
    return True


def _service(**kwargs: Any) -> None:  # pragma: no cover - a spy that must not run
    _RAN.append("service")


def _rows(**kwargs: Any) -> Any:  # pragma: no cover - a spy that must not run
    _RAN.append("list selector")
    return []


def _row(*, pk: int) -> Any:  # pragma: no cover - a spy that must not run
    _RAN.append("selector")
    return None


_BY_PK = Parameters.of(Parameter("pk", "integer", required=True))
# A read the provider fills, and one the dispatcher seeds from the call's
# context: neither is the caller's to send, so neither is described.
_SERVER_READS = Parameters.of(
    Parameter("owner", "string", required=True),
    Parameter("request", "any", reflected=True),
)


def _target() -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.RETRIEVE, selector=_row, reads=_BY_PK)


def _write(**fields: Any) -> ServiceSpec:
    defaults: dict[str, Any] = {
        "service": _service,
        "permissions": _OPEN,
        "validator": SerializerValidator(_NameIn),
        "reads": _SERVER_READS,
        "kwargs": _owner,
        "input_data": _slug,
        "preconditions": [_precondition],
        "affordances": [Affordance(code="closed", reason="Closed.", when=_open_now)],
    }
    return ServiceSpec(**{**defaults, **fields})


def _create() -> ServiceSpec:
    return _write()


def _update() -> ServiceSpec:
    return _write(instance_selector_spec=_target())


def _destroy() -> ServiceSpec:
    return ServiceSpec(
        service=_service,
        permissions=_OPEN,
        instance_selector_spec=_target(),
        preconditions=[_precondition],
    )


def _list() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=_rows,
        permissions=_OPEN,
        presenter=_PRESENTER,
        preconditions=[_precondition],
    )


def _retrieve() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=_row,
        reads=_BY_PK,
        permissions=_OPEN,
        presenter=_PRESENTER,
        preconditions=[_precondition],
    )


def _all_actions() -> dict[str, Any]:
    return {
        "list": _list(),
        "retrieve": _retrieve(),
        "create": _create(),
        "update": _update(),
        "destroy": _destroy(),
    }


_DETAIL = {"pk": "1"}
_LIST_ROUTE = {"get": "list", "post": "create"}
_DETAIL_ROUTE = {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}

# (base, its spec attributes, the router's action map or ``None`` for a
# standalone view, the route's captures, the ``Allow`` expected, the methods
# described in ``actions``).
_ROUTES = [
    pytest.param(
        ServiceCreateView, {"spec": _create()}, None, {}, {"POST"}, {"POST"}, id="create-view"
    ),
    pytest.param(
        ServiceUpdateView,
        {"spec": _update()},
        None,
        _DETAIL,
        {"PUT", "PATCH"},
        {"PUT"},
        id="update-view",
    ),
    pytest.param(
        ServiceDeleteView, {"spec": _destroy()}, None, _DETAIL, {"DELETE"}, set(), id="delete-view"
    ),
    pytest.param(
        SelectorListView, {"spec": _list()}, None, {}, {"GET", "HEAD"}, set(), id="list-view"
    ),
    pytest.param(
        SelectorRetrieveView,
        {"spec": _retrieve()},
        None,
        _DETAIL,
        {"GET", "HEAD"},
        set(),
        id="retrieve-view",
    ),
    pytest.param(
        ServiceViewSet,
        {"action_specs": _all_actions()},
        _LIST_ROUTE,
        {},
        {"GET", "HEAD", "POST"},
        {"POST"},
        id="service-viewset-list-route",
    ),
    pytest.param(
        ServiceViewSet,
        {"action_specs": _all_actions()},
        _DETAIL_ROUTE,
        _DETAIL,
        {"GET", "HEAD", "PUT", "PATCH", "DELETE"},
        {"PUT"},
        id="service-viewset-detail-route",
    ),
    pytest.param(
        SelectorViewSet,
        {"action_specs": {"list": _list()}},
        {"get": "list"},
        {},
        {"GET", "HEAD"},
        set(),
        id="selector-viewset-list-route",
    ),
    pytest.param(
        SelectorViewSet,
        {"action_specs": {"retrieve": _retrieve()}},
        {"get": "retrieve"},
        _DETAIL,
        {"GET", "HEAD"},
        set(),
        id="selector-viewset-detail-route",
    ),
]


def _view(base: type, attrs: dict[str, Any], actions: dict[str, str] | None) -> Any:
    view_cls = type("_Route", (base,), {"throttle_classes": [_Recorded], **attrs})
    return view_cls.as_view() if actions is None else view_cls.as_view(actions)


def _options(view: Any, captures: dict[str, str], **extra: Any) -> Any:
    return view(factory.options("/", **extra), **captures)


@pytest.mark.parametrize(("base", "attrs", "actions", "captures", "allow", "described"), _ROUTES)
def test_every_route_answers_options_from_its_spec(
    base: type,
    attrs: dict[str, Any],
    actions: dict[str, str] | None,
    captures: dict[str, str],
    allow: set[str],
    described: set[str],
) -> None:
    response = _options(_view(base, attrs, actions), captures)

    assert response.status_code == 200
    # ``initial()`` ran, and nothing of the spec's did.
    assert _RAN == ["throttle"]
    assert set(response["Allow"].split(", ")) == allow | {"OPTIONS"}
    assert {"name", "description", "renders", "parses"} <= set(response.data)
    assert set(response.data.get("actions", {})) == described
    for method in described:
        schema = response.data["actions"][method]
        assert schema["type"] == "object"
        # The caller's field is described; the key the ``kwargs`` provider
        # fills, the one ``input_data`` fills and the seeded ``request`` are not.
        assert set(schema["properties"]) >= {"name"}
        assert not set(schema["properties"]) & {"owner", "slug", "request"}
        # Under the edge's IGNORE an undeclared key is dropped, not refused.
        assert "additionalProperties" not in schema


class _RefuseWrites(PermissionCheck):
    """Refuses every principal: a caller the spec does not grant."""

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return False


def test_a_method_authorize_refuses_is_not_described() -> None:
    view = _view(
        ServiceUpdateView,
        {"spec": _write(permissions=[_RefuseWrites()], instance_selector_spec=_target())},
        None,
    )

    response = _options(view, _DETAIL)

    assert response.status_code == 200
    assert "actions" not in response.data or "PUT" not in response.data["actions"]
    # Refused for the description only: the method is still routed.
    assert set(response["Allow"].split(", ")) == {"PUT", "PATCH", "OPTIONS"}
    assert _RAN == ["throttle"]


def test_a_method_the_views_own_permission_classes_refuse_is_not_described() -> None:
    """DRF's own per-method check stays: ``IsAuthenticatedOrReadOnly`` lets an
    anonymous OPTIONS through and refuses the POST it would describe."""
    view = _view(
        ServiceCreateView,
        {"spec": _create(), "permission_classes": [IsAuthenticatedOrReadOnly]},
        None,
    )

    response = _options(view, {})

    assert response.status_code == 200
    assert "POST" not in response.data.get("actions", {})


class _RecordsItsContext(PermissionCheck):
    seen: list[dict[str, Any]] = []

    def has_permission(self, principal: Any, spec: Any, *, call_context: Any) -> bool:
        self.seen.append(call_context)
        return True


def test_authorize_is_asked_with_the_views_call_context() -> None:
    """The context is the OPTIONS request's own, built from the real request
    rather than the per-method clone DRF swaps in."""
    _RecordsItsContext.seen = []
    view = _view(ServiceCreateView, {"spec": _write(permissions=[_RecordsItsContext()])}, None)

    response = _options(view, {})

    assert response.status_code == 200
    assert "POST" in response.data["actions"]
    [context] = _RecordsItsContext.seen
    assert context["request"].method == "OPTIONS"
    assert context["view"].request is context["request"]


def test_a_method_the_view_does_not_allow_is_not_described() -> None:
    """Both verbs share the update view's spec; a view narrowing
    ``http_method_names`` to PATCH serves no PUT to describe."""
    view = _view(
        ServiceUpdateView, {"spec": _update(), "http_method_names": ["patch", "options"]}, None
    )

    response = _options(view, _DETAIL)

    assert response.status_code == 200
    assert set(response["Allow"].split(", ")) == {"PATCH", "OPTIONS"}
    assert "actions" not in response.data


@pytest.mark.parametrize(
    ("base", "method"), [(ServiceCreateView, "POST"), (ServiceUpdateView, "PUT")], ids=str
)
def test_a_drfs_spec_keeps_drfs_own_answer(base: type, method: str) -> None:
    """Until the drfs path goes, a drfs spec is described by DRF's metadata, off
    the view's ``serializer_class``, as before."""

    view = _view(
        base,
        {
            "spec": DrfsServiceSpec(service=_service, input_serializer=_NameIn),
            "serializer_class": AuthorSerializer,
            "get_object": lambda self: None,
        },
        None,
    )

    response = _options(view, {})

    assert response.status_code == 200
    assert set(response.data["actions"][method]) == {"id", "name"}
