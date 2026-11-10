"""OPTIONS against a viewset serving kernel specs.

DRF sets ``self.action = "metadata"`` for OPTIONS, an implicit action with no
handler behind it, and a CORS preflight is an OPTIONS request too, so every
route must answer one. A route serving a kernel spec is described from its
specs (``tests/views/test_spec_options.py`` holds the answer on every base);
this file holds what is particular to a viewset: which methods its routing
serves, the ``Allow`` it states, and the shapes a metadata pass probing the
view's serializer could not describe.
"""

from __future__ import annotations

from typing import Any, TypedDict

import pytest
from django_service_specs import (
    DEFAULT_POOL_SEEDS,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
    UnsetType,
)
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import (
    ActionSerializerResolver,
    ServiceViewSet,
    service_action,
)
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_PRESENTER = SerializerPresenter(AuthorSerializer)


class _NameIn(serializers.Serializer):
    name = serializers.CharField(max_length=20)


class _NeedsTenant(serializers.Serializer):
    """An input whose fields cannot be built without a key the view's input layer adds."""

    name = serializers.CharField()

    def get_fields(self) -> Any:
        fields = super().get_fields()
        _ = self.context["tenant"]
        return fields


class _OwnedRow(serializers.Serializer):
    name = serializers.CharField()
    owner = serializers.CharField()
    note = serializers.CharField()


class _MayOwn(TypedDict):
    owner: str | UnsetType


class _MayName(TypedDict):
    name: str | UnsetType


class _RowFill(TypedDict):
    owner: str
    note: str | UnsetType


def _may_own() -> _MayOwn:  # pragma: no cover - never called
    raise AssertionError


def _may_name() -> _MayName:  # pragma: no cover - never called
    raise AssertionError


def _row_fill() -> _RowFill:  # pragma: no cover - never called
    raise AssertionError


class _DenyAll(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return False


def _service(**kwargs: Any) -> None:  # pragma: no cover - never called
    raise AssertionError


def _row(*, pk: int) -> Any:  # pragma: no cover - never called
    raise AssertionError


def _rows() -> Any:  # pragma: no cover - never called
    raise AssertionError


_TARGET = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=_row,
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
)


def _create(validator: Any = _NameIn) -> ServiceSpec:
    return ServiceSpec(
        service=_service,
        permissions=_OPEN,
        validator=SerializerValidator(validator),
        presenter=_PRESENTER,
    )


def _update(**fields: Any) -> ServiceSpec:
    return ServiceSpec(
        service=_service,
        permissions=_OPEN,
        validator=SerializerValidator(_NameIn),
        presenter=_PRESENTER,
        instance_selector_spec=_TARGET,
        **fields,
    )


def _list() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST, selector=_rows, permissions=_OPEN, presenter=_PRESENTER
    )


def _viewset(base: type = ServiceViewSet, **attrs: Any) -> type:
    return type("_ViewSet", (base,), {"queryset": Author.objects.all(), **attrs})


def _options(viewset: type, actions: dict[str, str], **captures: Any) -> Any:
    return viewset.as_view(actions)(factory.options("/"), **captures)


def _allow(response: Any) -> set[str]:
    return set(response["Allow"].split(", "))


def _described(response: Any) -> dict[str, set[str]]:
    actions = response.data.get("actions", {})
    return {method: set(schema["properties"]) for method, schema in actions.items()}


def _schema(response: Any, method: str) -> dict[str, Any]:
    return response.data["actions"][method]


# ----- the defect: an implicit action with no handler -----


def test_options_on_a_kernel_viewset_answers_with_metadata() -> None:
    response = _options(_viewset(action_specs={"create": _create()}), {"post": "create"})
    assert response.status_code == 200
    assert response.data["name"]
    assert _described(response) == {"POST": {"name"}}


def test_options_is_gated_by_the_views_own_permission_classes() -> None:
    viewset = _viewset(action_specs={"create": _create()}, permission_classes=[_DenyAll])
    assert _options(viewset, {"post": "create"}).status_code == 403


def test_a_view_without_a_metadata_class_refuses_options() -> None:
    """``metadata_class = None`` turns OPTIONS off, as it does on DRF's own views."""
    viewset = _viewset(action_specs={"create": _create()}, metadata_class=None)
    response = _options(viewset, {"post": "create"})
    assert response.status_code == 405
    assert "OPTIONS" in _allow(response)


# ----- Allow names only what a spec serves -----


def test_allow_names_only_the_methods_a_spec_serves() -> None:
    """A router binds PUT, PATCH and DELETE to this package's own handlers on
    every detail route, and each answers 405 with no spec behind it, so none
    is listed; ``Allow`` is the same on the 405 itself."""
    viewset = _viewset(action_specs={"create": _create(), "list": _list()})
    actions = {
        "get": "list",
        "post": "create",
        "put": "update",
        "patch": "partial_update",
        "delete": "destroy",
    }
    response = _options(viewset, actions)
    assert response.status_code == 200
    assert _allow(response) == {"GET", "HEAD", "POST", "OPTIONS"}
    refused = viewset.as_view(actions)(factory.put("/", {"name": "x"}, format="json"))
    assert refused.status_code == 405
    assert _allow(refused) == {"GET", "HEAD", "POST", "OPTIONS"}


def test_patch_is_served_through_the_update_spec() -> None:
    viewset = _viewset(action_specs={"update": _update()})
    response = _options(viewset, {"put": "update", "patch": "partial_update"}, pk=1)
    assert _allow(response) == {"PUT", "PATCH", "OPTIONS"}
    assert _described(response) == {"PUT": {"name"}}


def test_a_partial_update_only_spec_serves_patch_alone() -> None:
    viewset = _viewset(action_specs={"partial_update": _update()})
    response = _options(viewset, {"put": "update", "patch": "partial_update"}, pk=1)
    assert _allow(response) == {"PATCH", "OPTIONS"}
    assert _described(response) == {}


def test_allow_keeps_a_views_own_handler_without_a_spec() -> None:
    """A handler the view defines itself is its own business: it stays in
    ``Allow`` and, with no spec, is not described."""

    class _ViewSet(ServiceViewSet):
        queryset = Author.objects.all()
        action_specs = {"list": _list()}

        @action(detail=False, methods=["post"])
        def ping(self, request: Any) -> Response:  # pragma: no cover - never called
            return Response()

    response = _options(_ViewSet, {"get": "list", "post": "ping"})
    assert _allow(response) == {"GET", "HEAD", "POST", "OPTIONS"}
    assert _described(response) == {}


def test_a_list_with_no_spec_and_no_serializer_leaves_allow() -> None:
    """``list`` with no spec falls back to DRF, which needs a serializer this viewset lacks
    beside its ``queryset``. So the handler answers 405 and ``Allow`` does not name it."""
    viewset = _viewset(action_specs={"create": _create()})
    response = _options(viewset, {"get": "list", "post": "create"})
    assert _allow(response) == {"POST", "OPTIONS"}


def test_a_list_with_no_spec_stays_allowed_where_its_fallback_can_run() -> None:
    """With a ``queryset`` and a ``serializer_class``, DRF's own ``list`` serves it."""
    viewset = _viewset(action_specs={"create": _create()}, serializer_class=AuthorSerializer)
    response = _options(viewset, {"get": "list", "post": "create"})
    assert _allow(response) == {"GET", "HEAD", "POST", "OPTIONS"}


# ----- which spec a method is described by -----


def test_a_service_action_s_kernel_spec_is_described() -> None:
    class _ViewSet(ServiceViewSet):
        queryset = Author.objects.all()

        @service_action(_create(), methods=["post"])
        def publish(self, request: Any) -> Any: ...

    response = _options(_ViewSet, {"post": "publish"})
    assert response.status_code == 200
    assert _described(response) == {"POST": {"name"}}


def test_a_route_capture_is_not_described_as_input() -> None:
    """The edge reads a declared capture from the route over anything the body
    sends, so a route carrying it does not ask the caller for it; on a route
    with no such capture it is still the caller's to send."""
    spec = ServiceSpec(
        service=_service,
        permissions=_OPEN,
        validator=SerializerValidator(_NameIn),
        reads=Parameters.of(Parameter("org", "string", required=True)),
    )
    viewset = _viewset(action_specs={"create": spec})
    captured = _options(viewset, {"post": "create"}, org="acme")
    assert _described(captured) == {"POST": {"name"}}
    uncaptured = _options(viewset, {"post": "create"})
    assert _described(uncaptured) == {"POST": {"name", "org"}}


def test_a_put_s_target_reads_are_not_described_as_input() -> None:
    """An update never reads its target's lookup from the body, only from the
    route and the query string, so PUT's body schema leaves it out on any
    route, a list route with no capture included."""
    viewset = _viewset(action_specs={"update": _update()})
    for captures in ({"pk": 1}, {}):
        assert _described(_options(viewset, {"put": "update"}, **captures)) == {"PUT": {"name"}}


def test_a_bulk_put_with_no_target_is_described() -> None:
    """A ``many`` update declares no target selector, so there is no lookup to
    leave out: its body is the list of rows."""
    spec = ServiceSpec(
        service=_service, permissions=_OPEN, validator=SerializerValidator(_NameIn), many=True
    )
    response = _options(_viewset(action_specs={"update": spec}), {"put": "update"})
    assert response.status_code == 200
    assert _described(response) == {"PUT": {spec.many_argument}}


def test_a_post_s_target_reads_are_not_described() -> None:
    """The edge drops a target lookup's reads from the body whatever the
    method, so a custom POST acting on a row does not ask for its lookup
    either, even on a route that does not carry it."""

    class _ViewSet(ServiceViewSet):
        queryset = Author.objects.all()

        @service_action(_update(), methods=["post"], detail=True)
        def publish(self, request: Any, pk: Any = None) -> Any: ...

    response = _options(_ViewSet, {"post": "publish"})
    assert _described(response) == {"POST": {"name"}}


# ----- what the caller is asked for, as dispatch demands it -----


def test_a_read_a_provider_may_decline_is_offered_and_not_required() -> None:
    """The ``kwargs`` provider may answer ``owner`` with ``UNSET``, so dispatch
    does not demand it of the caller, whose value is kept beneath the
    provider's answer: described, and not required."""
    spec = ServiceSpec(
        service=_service,
        permissions=_OPEN,
        validator=SerializerValidator(_NameIn),
        reads=Parameters.of(Parameter("owner", "string", required=True)),
        kwargs=_may_own,
    )
    response = _options(_viewset(action_specs={"create": spec}), {"post": "create"})
    schema = _schema(response, "POST")
    assert set(schema["properties"]) == {"name", "owner"}
    assert schema["required"] == ["name"]


def test_a_read_named_for_a_seed_the_view_registers_is_not_described() -> None:
    """``stamp`` is a reflected read the view's ``pool_seeds`` fill, so the
    kernel withholds it under those seeds; under the kernel's defaults it
    would be offered, which OPTIONS once built its answer with."""
    spec = ServiceSpec(
        service=_service,
        permissions=_OPEN,
        validator=SerializerValidator(_NameIn),
        reads=Parameters.of(Parameter("stamp", "string", reflected=True)),
    )
    seeds = DEFAULT_POOL_SEEDS.extend(stamp=lambda: "stamp")
    viewset = _viewset(action_specs={"create": spec}, pool_seeds=seeds)
    assert _described(_options(viewset, {"post": "create"})) == {"POST": {"name"}}


def test_a_field_input_data_may_decline_is_offered_and_not_required() -> None:
    spec = ServiceSpec(
        service=_service,
        permissions=_OPEN,
        validator=SerializerValidator(_NameIn),
        input_data=_may_name,
    )
    response = _options(_viewset(action_specs={"create": spec}), {"post": "create"})
    schema = _schema(response, "POST")
    assert set(schema["properties"]) == {"name"}
    assert "required" not in schema


def test_a_partial_spec_s_put_requires_none_of_its_fields() -> None:
    """A ``partial`` spec is dispatched partial on every method, so a PUT
    leaving a field out is not refused for it."""
    viewset = _viewset(action_specs={"update": _update(partial=True)})
    schema = _schema(_options(viewset, {"put": "update"}, pk=1), "PUT")
    assert set(schema["properties"]) == {"name"}
    assert "required" not in schema


def test_a_many_row_withholds_what_input_data_fills_and_relaxes_what_it_may() -> None:
    """``input_data`` is merged over every row: ``owner`` is never the
    caller's in any row, and ``note`` is described and not required."""
    spec = ServiceSpec(
        service=_service,
        permissions=_OPEN,
        validator=SerializerValidator(_OwnedRow),
        input_data=_row_fill,
        many=True,
    )
    response = _options(_viewset(action_specs={"create": spec}), {"post": "create"})
    rows = _schema(response, "POST")["properties"][spec.many_argument]["items"]
    assert set(rows["properties"]) == {"name", "note"}
    assert rows["required"] == ["name"]


def test_a_field_a_typed_input_data_fills_is_not_described() -> None:
    spec = ServiceSpec(
        service=_service,
        permissions=_OPEN,
        validator=SerializerValidator(_OwnedRow),
        input_data=_row_fill,
    )
    response = _options(_viewset(action_specs={"create": spec}), {"post": "create"})
    schema = _schema(response, "POST")
    assert set(schema["properties"]) == {"name", "note"}
    assert schema["required"] == ["name"]


# ----- what a serializer-probing metadata pass could not describe -----


def test_a_put_on_a_list_route_is_described_without_a_lookup() -> None:
    """A PUT routed on a URL with no lookup kwarg is described without
    ``get_object()``, which would end in DRF's ``URL keyword argument``
    assertion. The target is the spec's own selector, which OPTIONS never runs."""
    response = _options(_viewset(action_specs={"update": _update()}), {"put": "update"})
    assert response.status_code == 200
    assert "PUT" in _described(response)


def test_a_context_dependent_input_is_left_out_rather_than_a_500() -> None:
    """Built with DRF's base context, the input would end in the serializer's
    ``KeyError``. The method stays routed and is not described: its fields are
    known only to the call its view's input layer adds to."""

    class _ViewSet(ServiceViewSet):
        queryset = Author.objects.all()
        action_specs = {"create": _create(validator=_NeedsTenant)}

        def get_input_serializer_context(self) -> dict[str, Any]:  # pragma: no cover
            return {"tenant": "acme"}

    response = _options(_ViewSet, {"post": "create"})
    assert response.status_code == 200
    assert _allow(response) == {"POST", "OPTIONS"}
    assert _described(response) == {}


def test_a_spec_only_viewset_without_a_serializer_class_is_described() -> None:
    """A ``create`` with no serializer to resolve is described from its spec,
    never reaching ``GenericAPIView.get_serializer_class``'s assertion."""
    viewset = type("_ViewSet", (ServiceViewSet,), {"action_specs": {"create": _create()}})
    response = _options(viewset, {"post": "create"})
    assert response.status_code == 200
    assert _described(response) == {"POST": {"name"}}


def test_the_resolver_after_generic_viewset_still_cannot_describe() -> None:
    """Listed after ``GenericViewSet``, the package's bases come after DRF's
    ``options()`` in the MRO, so DRF's own metadata answers and probes
    ``serializer_class`` as it always has: the one shape still ending in DRF's
    assertion. Listing the package's base first is the fix."""
    viewset = type(
        "_ViewSet",
        (GenericViewSet, ActionSerializerResolver),
        {"action_specs": {"create": _create()}, "create": _service},
    )
    with pytest.raises(AssertionError, match="serializer_class"):
        _options(viewset, {"post": "create"})
