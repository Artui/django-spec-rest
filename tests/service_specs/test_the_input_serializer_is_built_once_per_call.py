"""A call's input serializer is built for the call's own body, row and context.

DRF's view builds one serializer for a request, with the request's data, the
row it updates and its context, so a ``get_fields`` or an ``__init__`` reading
``self.initial_data``, ``self.instance`` or ``self.partial`` reads the call's.
A kernel spec whose Validator is a ``SerializerValidator`` keeps that: the
fields the kernel checks the arguments against are the fields the serializer
validates with over a live view, where the serializer is built, and queries as it
is built, once. Through the kernel's own ``dispatch`` there is no call to
describe the serializer for, so a serializer whose fields depend on the body, the
row or ``partial`` is not covered off HTTP: that is the decided answer.
"""

from __future__ import annotations

import collections
from collections.abc import Callable
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth.models import AnonymousUser
from django_service_specs import (
    DispatchResult,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.dispatch import dispatch as kernel_dispatch
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView, ServiceUpdateView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Post, Tag

BUILT: collections.Counter[str] = collections.Counter()
_OPEN = (Unrestricted(),)


class _Counted(serializers.Serializer):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        BUILT[type(self).__name__] += 1
        super().__init__(*args, **kwargs)


class InitialDataKind(_Counted):
    """A field the body's own ``kind`` adds, read off ``initial_data`` as the fields are built."""

    kind = serializers.CharField()

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        if self.initial_data.get("kind") == "long":
            fields["extra"] = serializers.CharField()
        return fields


class InitialDataInInit(_Counted):
    """``initial_data`` read as the serializer is built."""

    kind = serializers.CharField()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.kind_sent = self.initial_data["kind"]


class InstancePk(_Counted):
    """The row's ``pk`` read as the fields are built."""

    title = serializers.CharField()

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["title"].help_text = f"for {self.instance.pk}"
        return fields


class InstanceAddsField(_Counted):
    """A field only an update takes."""

    title = serializers.CharField(required=False)

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        if self.instance is not None:
            fields["reason"] = serializers.CharField()
        return fields


class InstanceMakesReadOnly(_Counted):
    """A field an update never writes."""

    title = serializers.CharField()
    body = serializers.CharField(required=False)

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        if self.instance is not None:
            fields["title"] = serializers.CharField(read_only=True)
        return fields


class PartialAddsField(_Counted):
    """A field only a partial call takes."""

    title = serializers.CharField(required=False)

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        if self.partial:
            fields["note"] = serializers.CharField()
        return fields


class Row(_Counted):
    kind = serializers.CharField()


class QueriesAsBuilt(_Counted):
    """One query each time the serializer is built."""

    title = serializers.CharField()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        list(Tag.objects.all()[:1])


class LimitFromContext(_Counted):
    """A bound read off the context, tolerant of a context that lacks it."""

    title = serializers.CharField()

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        limit = self.context.get("limit")
        if limit is not None:
            fields["title"] = serializers.CharField(max_length=limit)
        return fields


class _Echo(serializers.Serializer):
    """What the service returned, as it returned it."""

    def to_representation(self, instance: Any) -> Any:
        return instance


def _created(*, data: Any) -> dict[str, Any]:
    return {"got": dict(data)}


def _updated(*, instance: Post, data: Any) -> dict[str, Any]:
    return {"got": dict(data), "pk": instance.pk}


_LOOKUP = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda pk: Post.objects.filter(pk=pk),
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
)


def _spec(
    serializer: type[serializers.Serializer],
    *,
    update: bool = False,
    context: Callable[..., Any] | None = None,
    **options: Any,
) -> ServiceSpec:
    return ServiceSpec(
        service=_updated if update else _created,
        validator=SerializerValidator(serializer, serializer_context=context),
        presenter=SerializerPresenter(_Echo),
        permissions=_OPEN,
        atomic=False,
        **options,
    )


def _by_lookup(serializer: type[serializers.Serializer], **options: Any) -> ServiceSpec:
    """An update whose row is the spec's own lookup's: a kernel spec's target is its
    ``instance_selector_spec``'s, never the view's ``get_object()``."""
    return _spec(serializer, update=True, instance_selector_spec=_LOOKUP, **options)


def _many_spec() -> ServiceSpec:
    return ServiceSpec(
        service=lambda *, data: [dict(row) for row in data],
        validator=SerializerValidator(Row),
        presenter=SerializerPresenter(_Echo),
        many=True,
        permissions=_OPEN,
        atomic=False,
    )


_factory = APIRequestFactory()


class _Open:
    """The view's own permission classes, none here, as the spine's views answer them:
    ``MutationFlowMixin.get_permissions`` reads a drfs-only spec field."""

    permission_classes: Any = []
    authentication_classes: Any = []

    def get_permissions(self) -> list[Any]:
        return []


def _create(spec: ServiceSpec, body: Any, **request: Any) -> Any:
    view = type("_View", (_Open, ServiceCreateView), {"spec": spec}).as_view()
    return view(_factory.post("/", body, **({"format": "json"} | request)))


def _lookup_update(spec: ServiceSpec, body: Any, post: Post) -> Any:
    """A ``PATCH`` whose row the spec's own target lookup finds, from the route's ``pk``."""
    view = type("_View", (_Open, ServiceUpdateView), {"spec": spec}).as_view()
    return view(_factory.patch("/", body, format="json"), pk=post.pk)


def _sync(spec: Any, *, arguments: Any, **kwargs: Any) -> DispatchResult:
    return kernel_dispatch(spec, principal=AnonymousUser(), arguments=arguments, **kwargs)


def _async(spec: Any, *, arguments: Any, **kwargs: Any) -> DispatchResult:
    return async_to_sync(adispatch)(spec, principal=AnonymousUser(), arguments=arguments, **kwargs)


_CORES = pytest.mark.parametrize("dispatch", [_sync, _async], ids=["sync", "async"])


@pytest.fixture
def post(db: Any) -> Post:
    BUILT.clear()
    return Post.objects.create(title="t")


@pytest.fixture(autouse=True)
def _counted() -> None:
    BUILT.clear()


# Over a live view the edge describes a kernel spec's serializer for
# ``parameters()`` with no body, no row and ``partial`` unset, so a field only
# the body, the row or a partial call adds is not among the parameters. A field
# only the row or a partial call adds still validates, unmarked below: the
# kernel drops it from its arguments under the edge's ``IGNORE``, but the
# serializer binds the request's body, which holds it. Closing it takes the
# edge describing the serializer bound to the call's body, row and flags.
_UNBOUND = pytest.mark.xfail(
    strict=True,
    reason=(
        "the kernel route describes a kernel spec's serializer for parameters() with no "
        "body, no "
        "row and partial unset: a field the body or the row adds is refused, or dropped "
        "under the edge's IGNORE so its value never reaches the service, a field an "
        "update never writes is required, and a serializer reading either raises"
    ),
)
_BUILT_AGAIN = pytest.mark.xfail(
    strict=True,
    reason=(
        "the kernel route describes a kernel spec's serializer for parameters() and its "
        "SerializerValidator builds another to validate with, so the call builds it, and "
        "queries as it is built, more than once"
    ),
)


class TestOverALiveView:
    @_UNBOUND
    def test_a_field_the_body_adds_validates(self, db: Any) -> None:
        response = _create(_spec(InitialDataKind), {"kind": "long", "extra": "x"})

        assert response.status_code == 201, response.data
        assert response.data == {"got": {"kind": "long", "extra": "x"}}

    @_UNBOUND
    def test_a_serializer_reading_its_body_as_it_is_built_validates(self, db: Any) -> None:
        response = _create(_spec(InitialDataInInit), {"kind": "k"})

        assert response.status_code == 201, response.data

    def test_a_field_only_a_partial_call_takes_validates(self, post: Post) -> None:
        response = _lookup_update(_by_lookup(PartialAddsField, partial=True), {"note": "n"}, post)

        assert response.status_code == 200, response.data
        assert response.data["got"] == {"note": "n"}

    @_UNBOUND
    def test_a_form_body_is_the_body_the_fields_are_built_for(self, db: Any) -> None:
        response = _create(
            _spec(InitialDataKind), {"kind": "long", "extra": "x"}, format="multipart"
        )

        assert response.status_code == 201, response.data
        assert response.data == {"got": {"kind": "long", "extra": "x"}}
        assert BUILT == {"InitialDataKind": 1}

    @_UNBOUND
    def test_a_serializer_reading_the_row_its_lookup_finds_validates(self, post: Post) -> None:
        response = _lookup_update(_by_lookup(InstancePk), {"title": "n"}, post)

        assert response.status_code == 200, response.data
        assert response.data == {"got": {"title": "n"}, "pk": post.pk}

    def test_a_field_added_for_the_row_its_lookup_finds_validates(self, post: Post) -> None:
        response = _lookup_update(_by_lookup(InstanceAddsField), {"reason": "why"}, post)

        assert response.status_code == 200, response.data
        assert response.data["got"] == {"reason": "why"}


class TestAnUpdateOverALiveViewIsDescribedForItsRow:
    """The one case of the description the kernel route already gets right.

    The row the spec's own lookup finds is the one the shape check's description sees, so a
    field that is read-only on an update is not required of the body. It stays
    unmarked beside the cases that still fail: it holds only if the description the
    shape check reads sees the row (without it ``title`` is required and the call is
    a ``400``)."""

    def test_a_field_an_update_never_writes_is_not_required(self, post: Post) -> None:
        response = _lookup_update(_by_lookup(InstanceMakesReadOnly), {"body": "b"}, post)

        assert response.status_code == 200, response.data
        assert response.data["got"] == {"body": "b"}


@_BUILT_AGAIN
class TestBuiltOnceOverALiveView:
    # ``Row`` reads neither the body nor the row as it is built, so each of these
    # counts builds and nothing else: the description gap the live-view cases above
    # name would fail a serializer that reads either before the count was reached.
    def test_a_create(self, db: Any) -> None:
        response = _create(_spec(Row), {"kind": "k"})

        assert response.status_code == 201, response.data
        assert BUILT == {"Row": 1}

    def test_an_update(self, post: Post) -> None:
        response = _lookup_update(_by_lookup(Row), {"kind": "n"}, post)

        assert response.status_code == 200, response.data
        assert BUILT == {"Row": 1}

    def test_a_many_call(self, db: Any) -> None:
        spec = _many_spec()
        rows = [{"kind": "a"}, {"kind": "b"}]
        _create(spec, rows)

        BUILT.clear()
        response = _create(spec, rows)

        assert response.status_code == 201, response.data
        assert BUILT == {"Row": 1}

    def test_its_queries_run_once(self, db: Any, django_assert_num_queries: Any) -> None:
        spec = _spec(QueriesAsBuilt)

        with django_assert_num_queries(1):
            response = _create(spec, {"title": "a"})

        assert response.status_code == 201, response.data


class TestAContextCallableTheDescriptionCannotAsk:
    """A callable taking ``**kwargs`` is asked by the serializer that validates.

    The description holds none of the call's seeds, so it reads the fields
    without the callable's answer, and the serializer that validates is built
    with it: the limit the answer sets is the one the body is refused by.
    """

    @_CORES
    def test_through_the_kernel_s_dispatch(
        self, dispatch: Callable[..., DispatchResult], db: Any
    ) -> None:
        spec = _spec(LimitFromContext, context=lambda **_: {"limit": 2})

        with pytest.raises(InvalidArguments) as caught:
            dispatch(spec, arguments={"title": "abc"})

        assert "title" in caught.value.detail

    def test_over_a_live_view(self, db: Any) -> None:
        response = _create(
            _spec(LimitFromContext, context=lambda **_: {"limit": 2}), {"title": "abc"}
        )

        assert response.status_code == 400
        assert "title" in response.data
