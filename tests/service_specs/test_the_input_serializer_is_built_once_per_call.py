"""A call's input serializer is built for the call's own body, row and context.

DRF's view builds one serializer for a request, with the request's data, the
row it updates and its context, so a ``get_fields`` or an ``__init__`` reading
``self.initial_data``, ``self.instance`` or ``self.partial`` reads the call's.
A kernel spec whose Validator is a ``SerializerValidator`` keeps that: the
fields the kernel checks the arguments against are the fields the serializer
validates with, over a live view and through the kernel's own ``dispatch``, and
over a live view the serializer is built, and queries as it is built, once.
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
    UnknownArguments,
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
    permissions=_OPEN,
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
_POLICIES = pytest.mark.parametrize(
    "policy", [UnknownArguments.IGNORE, UnknownArguments.REJECT], ids=["ignore", "reject"]
)


@pytest.fixture
def post(db: Any) -> Post:
    BUILT.clear()
    return Post.objects.create(title="t")


@pytest.fixture(autouse=True)
def _counted() -> None:
    BUILT.clear()


# Over a live view the edge could bind the description to the call, and does
# not: it sets no ``describe_binding`` for a kernel spec, so the Validator
# describes its serializer for ``parameters()`` afresh, with no body, no row and
# ``partial`` unset. Closing it takes the edge (``dispatch/kernel_edge.py``)
# setting the binding and the serializer walk (``describe_serializer``,
# ``describe_with``) reading it there.
_UNBOUND = pytest.mark.xfail(
    strict=True,
    reason=(
        "the kernel route's edge sets no describe_binding for a kernel spec, so its "
        "SerializerValidator describes the serializer for parameters() with no body, no "
        "row and partial unset: a field the body or the row adds is refused, a field an "
        "update never writes is required, and a serializer reading either raises"
    ),
)
# Through the kernel's own ``dispatch`` there is no edge at all: the kernel asks
# ``Validator.parameters()``, which takes nothing of the call, for its shape
# check before ``validated()`` is handed the arguments and the target. So no
# code in this package can describe the serializer for the call's body, row or
# ``partial`` there; it would take a kernel seat handing the Validator the call
# before the shape check, or these cases drop.
_NO_CALL_TO_DESCRIBE_FOR = pytest.mark.xfail(
    strict=True,
    reason=(
        "the kernel's dispatch asks Validator.parameters() for its shape check with "
        "nothing of the call, before validated() sees the arguments or the target, so "
        "a serializer whose fields depend on the body, the row or partial cannot be "
        "described for the call off HTTP"
    ),
)
_BUILT_AGAIN = pytest.mark.xfail(
    strict=True,
    reason=(
        "a kernel spec's SerializerValidator builds its serializer afresh for every "
        "parameters() read on the kernel route, so the call builds it, and queries as it "
        "is built, more than once"
    ),
)


@_UNBOUND
class TestOverALiveView:
    def test_a_field_the_body_adds_validates(self, db: Any) -> None:
        response = _create(_spec(InitialDataKind), {"kind": "long", "extra": "x"})

        assert response.status_code == 201, response.data
        assert response.data == {"got": {"kind": "long", "extra": "x"}}

    def test_a_serializer_reading_its_body_as_it_is_built_validates(self, db: Any) -> None:
        response = _create(_spec(InitialDataInInit), {"kind": "k"})

        assert response.status_code == 201, response.data

    def test_a_field_only_a_partial_call_takes_validates(self, post: Post) -> None:
        response = _lookup_update(_by_lookup(PartialAddsField, partial=True), {"note": "n"}, post)

        assert response.status_code == 200, response.data
        assert response.data["got"] == {"note": "n"}

    def test_a_form_body_is_the_body_the_fields_are_built_for(self, db: Any) -> None:
        response = _create(
            _spec(InitialDataKind), {"kind": "long", "extra": "x"}, format="multipart"
        )

        assert response.status_code == 201, response.data
        assert response.data == {"got": {"kind": "long", "extra": "x"}}
        assert BUILT == {"InitialDataKind": 1}

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


@_NO_CALL_TO_DESCRIBE_FOR
@_CORES
class TestThroughTheKernelsDispatch:
    def test_a_field_the_body_adds_validates(self, dispatch: Callable[..., DispatchResult]) -> None:
        result = dispatch(_spec(InitialDataKind), arguments={"kind": "long", "extra": "x"})

        assert result.value == {"got": {"kind": "long", "extra": "x"}}

    def test_a_serializer_reading_its_body_as_it_is_built_validates(
        self, dispatch: Callable[..., DispatchResult]
    ) -> None:
        assert dispatch(_spec(InitialDataInInit), arguments={"kind": "k"}).value == {
            "got": {"kind": "k"}
        }

    def test_a_field_an_update_never_writes_is_not_required(
        self, dispatch: Callable[..., DispatchResult], post: Post
    ) -> None:
        result = dispatch(_by_lookup(InstanceMakesReadOnly), arguments={"pk": post.pk, "body": "b"})

        assert result.value["got"] == {"body": "b"}

    def test_a_field_only_a_partial_call_takes_is_no_unknown_argument(
        self, dispatch: Callable[..., DispatchResult], post: Post
    ) -> None:
        result = dispatch(
            _by_lookup(PartialAddsField, partial=True), arguments={"pk": post.pk, "note": "n"}
        )

        assert result.value["got"] == {"note": "n"}

    def test_a_field_the_server_s_value_adds_is_the_call_s(
        self, dispatch: Callable[..., DispatchResult], db: Any
    ) -> None:
        spec = _spec(InitialDataKind, input_data=lambda: {"kind": "long"})

        result = dispatch(spec, arguments={"kind": "short", "extra": "x"})

        assert result.value == {"got": {"kind": "long", "extra": "x"}}

    @_POLICIES
    def test_a_serializer_reading_the_row_its_lookup_finds_validates(
        self, dispatch: Callable[..., DispatchResult], post: Post, policy: UnknownArguments
    ) -> None:
        result = dispatch(
            _by_lookup(InstancePk),
            arguments={"pk": post.pk, "title": "n"},
            unknown_arguments=policy,
        )

        assert result.value == {"got": {"title": "n"}, "pk": post.pk}

    @_POLICIES
    def test_a_field_added_for_the_row_its_lookup_finds_validates(
        self, dispatch: Callable[..., DispatchResult], post: Post, policy: UnknownArguments
    ) -> None:
        result = dispatch(
            _by_lookup(InstanceAddsField),
            arguments={"pk": post.pk, "reason": "why"},
            unknown_arguments=policy,
        )

        assert result.value["got"] == {"reason": "why"}

    def test_a_row_its_lookup_finds_is_the_one_described(
        self, dispatch: Callable[..., DispatchResult], post: Post
    ) -> None:
        result = dispatch(_by_lookup(InstanceMakesReadOnly), arguments={"pk": post.pk, "body": "b"})

        assert result.value == {"got": {"body": "b"}, "pk": post.pk}

    def test_a_missing_row_is_not_found(
        self, dispatch: Callable[..., DispatchResult], post: Post
    ) -> None:
        result = dispatch(_by_lookup(InstancePk), arguments={"pk": post.pk + 1, "title": "n"})

        assert result.kind == "not_found"


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
