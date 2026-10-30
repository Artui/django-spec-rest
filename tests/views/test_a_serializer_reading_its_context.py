"""A kernel spec's input serializer reading ``self.context`` unguarded, over HTTP.

DRF builds an input serializer with its view's context, so a serializer may
read the request or the view while it is built or while its fields are: a
``PrimaryKeyRelatedField`` scoped to the caller, a field a query value turns
on, a field the route names. A ``SerializerValidator`` describes its
serializer to learn its parameters, and describes it with the call's own
request and view, so each answers as the view always did. The scope holds in
the serializer that validates: a caller picks a row of its own and is refused
another's.

The call's context is meant to be DRF's serializer context, one dict per
request handed to every serializer of the call as the very object.
``test_the_call_s_context_is_every_serializer_s_context`` holds that as a
strict xfail: the serializers and the service share one dict, but not yet the
one ``get_serializer_context()`` returned.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User
from django_service_specs import ServiceSpec, Unrestricted
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.present import present
from rest_framework import serializers
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest import ServiceCreateView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.service_specs.utils import edge_call_state
from tests.testapp.models import Post

_factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _ScopedToTheCaller(serializers.Serializer):
    """A ``PrimaryKeyRelatedField`` scoped to the caller, set as the serializer is built."""

    post = serializers.PrimaryKeyRelatedField(queryset=Post.objects.none())

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        user = self.context["request"].user
        self.fields["post"].queryset = Post.objects.filter(title=user.username)


class _FieldsFromTheQuery(serializers.Serializer):
    """A field a query value turns on, read unguarded while the fields are built."""

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        if self.context["request"].query_params.get("extra"):
            fields["extra"] = serializers.CharField()
        return fields


class _FieldsFromTheView(serializers.Serializer):
    """A field named by the view's route, read unguarded while the fields are built."""

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields[self.context["view"].kwargs.get("field", "title")] = serializers.CharField()
        return fields


class _ScopedByTheSpec(serializers.Serializer):
    """Reads, unguarded as it is built, a key only the seat's context callable gives."""

    title = serializers.CharField()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["title"].help_text = self.context["tenant"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        return {**attrs, "tenant": self.fields["title"].help_text}


class _FieldsFromTheSpec(serializers.Serializer):
    """A field named by a key only the seat's context callable gives."""

    def get_fields(self) -> dict[str, serializers.Field]:
        return {self.context["field"]: serializers.CharField()}


def _spec(
    serializer: type[serializers.Serializer], seen: dict[str, Any], provider: Any = None
) -> ServiceSpec:
    def service(*, data: Any) -> None:
        seen["data"] = dict(data)

    return ServiceSpec(
        service=service,
        permissions=_OPEN,
        validator=SerializerValidator(serializer, serializer_context=provider),
        atomic=False,
    )


class _KernelCreateView(ServiceCreateView):
    """``get_permissions`` answers the view's own classes, as for a spec setting none.

    ``MutationFlowMixin.get_permissions`` reads ``spec.permission_classes``,
    which a kernel spec has no attribute for.
    """

    permission_classes: list[Any] = []

    def get_permissions(self) -> list[Any]:
        return [permission() for permission in self.permission_classes]


def _create(spec: ServiceSpec, body: dict[str, Any], user: User, url: str = "/") -> Any:
    request = _factory.post(url, body, format="json")
    force_authenticate(request, user=user)
    return type("_View", (_KernelCreateView,), {"spec": spec}).as_view()(request)


_DESCRIBED_WITH_NO_CALL = pytest.mark.xfail(
    strict=True,
    reason=(
        "The serializer is described with the call's request and view, but a seat's "
        "serializer_context that declares the whole pool is left out of the description, "
        "so a serializer that cannot be built without that callable's keys raises KeyError."
    ),
)


@pytest.fixture
def owner(db: Any) -> User:
    return User.objects.create(username="owner")


@pytest.fixture
def own_post(owner: User) -> Post:
    return Post.objects.create(title="owner")


@pytest.fixture
def other_post(db: Any) -> Post:
    return Post.objects.create(title="someone-else")


def test_a_live_view_scopes_the_field_to_the_caller(
    owner: User, own_post: Post, other_post: Post
) -> None:
    seen: dict[str, Any] = {}
    spec = _spec(_ScopedToTheCaller, seen)

    assert _create(spec, {"post": own_post.pk}, owner).status_code == 204
    assert seen == {"data": {"post": own_post}}

    refused = _create(spec, {"post": other_post.pk}, owner)
    assert refused.status_code == 400
    assert refused.data["post"][0].code == "does_not_exist"


def test_a_live_view_builds_the_fields_from_its_query_string(owner: User) -> None:
    seen: dict[str, Any] = {}

    response = _create(_spec(_FieldsFromTheQuery, seen), {"extra": "e"}, owner, url="/?extra=1")

    assert response.status_code == 204, response.data
    assert seen == {"data": {"extra": "e"}}


def test_a_live_view_builds_the_fields_from_its_route(owner: User) -> None:
    seen: dict[str, Any] = {}

    response = _create(_spec(_FieldsFromTheView, seen), {"title": "t"}, owner)

    assert response.status_code == 204, response.data
    assert seen == {"data": {"title": "t"}}


def test_a_live_view_describes_with_the_seat_s_context(owner: User) -> None:
    seen: dict[str, Any] = {}

    spec = _spec(_ScopedByTheSpec, seen, lambda: {"tenant": "acme"})
    assert _create(spec, {"title": "t"}, owner).status_code == 204
    assert seen == {"data": {"title": "t", "tenant": "acme"}}

    spec = _spec(_FieldsFromTheSpec, seen, lambda: {"field": "name"})
    assert _create(spec, {"name": "n"}, owner).status_code == 204
    assert seen == {"data": {"name": "n"}}


def _whole_pool(asked: list[None], **answer: str) -> Any:
    def provider(**pool: Any) -> dict[str, Any]:
        asked.append(None)
        return answer

    return provider


@_DESCRIBED_WITH_NO_CALL
def test_a_live_view_describes_a_serializer_needing_a_whole_pool_callable(owner: User) -> None:
    """A serializer that cannot be built without the callable's keys is described with them."""
    seen: dict[str, Any] = {}
    asked: list[None] = []

    spec = _spec(_ScopedByTheSpec, seen, _whole_pool(asked, tenant="acme"))
    assert _create(spec, {"title": "t"}, owner).status_code == 204
    assert seen == {"data": {"title": "t", "tenant": "acme"}}
    assert asked

    spec = _spec(_FieldsFromTheSpec, seen, _whole_pool(asked, field="name"))
    assert _create(spec, {"name": "n"}, owner).status_code == 204
    assert seen == {"data": {"name": "n"}}


class _FailsToBuild(serializers.Serializer):
    """A ``get_fields`` that fails for a reason of its own, whatever context it has."""

    def get_fields(self) -> dict[str, serializers.Field]:
        raise KeyError("a key the serializer's own code lacks")


def test_a_serializer_its_description_cannot_build_raises_as_it_is(owner: User) -> None:
    """With no context callable to ask, the description is not rebuilt: what the
    serializer raised is what the view raises, not a refusal of the call."""
    seen: dict[str, Any] = {}

    with pytest.raises(KeyError, match="a key the serializer's own code lacks"):
        _create(_spec(_FailsToBuild, seen), {"name": "n"}, owner)

    assert seen == {}


class _WritesToItsContext(serializers.Serializer):
    title = serializers.CharField()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        self.context["written"] = "by-validate"
        return attrs


class _ReadsItsContext(serializers.Serializer):
    title = serializers.CharField()
    written = serializers.SerializerMethodField()

    def get_written(self, value: Any) -> Any:
        return self.context.get("written")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "The serializers and the service share one dict now, but it is the one "
        "fill_call_context builds (view_call_context, views/utils.py), not the object "
        "get_serializer_context() returned, so only the final identity assertion fails."
    ),
)
def test_the_call_s_context_is_every_serializer_s_context(owner: User) -> None:
    """A key the input serializer's ``validate()`` writes is read by the service and by
    the output serializer, and the context is the object ``get_serializer_context()``
    returned."""
    seen: dict[str, Any] = {}

    def service(*, data: Any, call_context: dict[str, Any]) -> dict[str, Any]:
        seen["service"] = call_context.get("written")
        seen["call_context"] = call_context
        return {"title": data["title"]}

    class _View(_KernelCreateView):
        spec = ServiceSpec(
            service=service,
            permissions=_OPEN,
            validator=SerializerValidator(_WritesToItsContext),
            presenter=SerializerPresenter(_ReadsItsContext),
            atomic=False,
        )

        def get_serializer_context(self) -> dict[str, Any]:
            context = super().get_serializer_context()
            seen.setdefault("returned", context)
            return context

    request = _factory.post("/", {"title": "t"}, format="json")
    force_authenticate(request, user=owner)
    response = _View.as_view()(request)

    assert response.status_code == 201
    assert seen["service"] == "by-validate"
    assert response.data["written"] == "by-validate"
    assert seen["call_context"] is seen["returned"]


class _RecordsItsRequest(serializers.Serializer):
    title = serializers.CharField()

    def to_representation(self, instance: Any) -> Any:
        _PRESENTED_UNDER.append(self.context["request"])
        return super().to_representation(instance)


_PRESENTED_UNDER: list[Any] = []

_ROWS = ServiceSpec(
    service=lambda: [{"title": "a"}, {"title": "b"}],
    permissions=_OPEN,
    presenter=SerializerPresenter(_RecordsItsRequest),
    returns_many=True,
    atomic=False,
)


def test_a_kernel_call_inside_the_service_presents_every_row_under_one_offline_request(
    owner: User,
) -> None:
    """A kernel call the service makes carries no request, so each row is
    presented under an offline request for the principal it was handed, and the
    rows of the call share the one the edge call built for it."""
    _PRESENTED_UNDER.clear()

    def service(*, data: Any) -> None:
        present(_ROWS, dispatch(_ROWS, principal=owner, arguments={}))

    assert _create(_spec_of(service), {}, owner).status_code == 204
    first, second = _PRESENTED_UNDER
    assert first is second
    assert first.user is owner


def _spec_of(service: Any) -> ServiceSpec:
    return ServiceSpec(service=service, permissions=_OPEN, atomic=False)


def test_a_kernel_call_for_another_principal_is_presented_under_its_own_offline_request(
    owner: User,
) -> None:
    """Two kernel calls the service makes with one arguments object, for two
    principals: each is presented under an offline request for its own, so a
    serializer reading ``request.user`` never reads the other's."""
    _PRESENTED_UNDER.clear()
    other = User.objects.create(username="other")
    arguments: dict[str, Any] = {}

    def service(*, data: Any) -> None:
        for principal in (owner, other):
            present(_ROWS, dispatch(_ROWS, principal=principal, arguments=arguments))

    assert _create(_spec_of(service), {}, owner).status_code == 204
    assert [request.user for request in _PRESENTED_UNDER] == [owner, owner, other, other]


_VALIDATED_UNDER: list[Any] = []
_DESCRIBED_UNDER: list[Any] = []


class _ReadsItsRequestWhileValidating(serializers.Serializer):
    title = serializers.CharField()

    def get_fields(self) -> dict[str, Any]:
        if not hasattr(self, "initial_data"):
            _DESCRIBED_UNDER.append((self.context["request"], self.context["view"]))
        return super().get_fields()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        _VALIDATED_UNDER.append((self.context["request"], self.context["view"]))
        return attrs


_TITLED = ServiceSpec(
    service=lambda *, title: None,
    permissions=_OPEN,
    validator=SerializerValidator(_ReadsItsRequestWhileValidating),
    atomic=False,
)


def test_a_kernel_call_for_another_principal_never_validates_under_the_view_s_request(
    owner: User,
) -> None:
    """Only the edge's own call reads the view's request and view: a kernel call
    the service makes for another principal validates under the offline pair
    for that principal, as it would outside the view."""
    _VALIDATED_UNDER.clear()
    other = User.objects.create(username="other")

    def service(*, data: Any) -> None:
        dispatch(_TITLED, principal=other, arguments={"title": "t"})

    assert _create(_spec_of(service), {}, owner).status_code == 204
    ((request, view),) = _VALIDATED_UNDER
    assert request.user == other
    assert not isinstance(view, ServiceCreateView)


def test_a_kernel_call_for_another_principal_is_never_described_under_the_view_s_request(
    owner: User,
) -> None:
    """The parameters a kernel call the service makes are read off a description
    of its serializer, and that description is not the edge's own call's either:
    it is built as outside any call, with no request and no view."""
    _DESCRIBED_UNDER.clear()
    other = User.objects.create(username="other")

    def service(*, data: Any) -> None:
        dispatch(_TITLED, principal=other, arguments={"title": "t"})

    assert _create(_spec_of(service), {}, owner).status_code == 204
    assert _DESCRIBED_UNDER
    assert all(pair == (None, None) for pair in _DESCRIBED_UNDER)


_SAME_SEEN: list[tuple[Any, Any, Any]] = []


class _ReadsItsCaller(serializers.Serializer):
    title = serializers.CharField()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        _SAME_SEEN.append((attrs["title"], self.context["request"], self.context["view"]))
        return attrs


def _dispatches_itself_for_another(*, title: str, user: Any) -> None:
    # The edge dispatches this very spec, Validator and all: a JSON body and
    # nothing for the recording twin to wrap, so the twin is the spec itself.
    assert edge_call_state().validator is _SAME.validator
    if user.username == "owner":
        other = User.objects.get(username="other")
        dispatch(_SAME, principal=other, arguments={"title": "inner"})


_SAME = ServiceSpec(
    service=_dispatches_itself_for_another,
    permissions=_OPEN,
    validator=SerializerValidator(_ReadsItsCaller),
    atomic=False,
)


def test_a_kernel_call_of_the_view_s_own_spec_for_another_principal_validates_offline(
    owner: User,
) -> None:
    """The service dispatches the view's own spec, the very Validator the edge
    dispatched, for another principal: that call is not the edge's, so it
    validates under the offline pair for its own principal, never the view's
    request and view."""
    _SAME_SEEN.clear()
    other = User.objects.create(username="other")

    assert _create(_SAME, {"title": "outer"}, owner).status_code == 204
    (_, outer_request, outer_view), (_, inner_request, inner_view) = _SAME_SEEN
    assert outer_request.user == owner
    assert isinstance(outer_view, ServiceCreateView)
    assert inner_request.user == other
    assert not isinstance(inner_view, ServiceCreateView)


def test_a_kernel_call_of_the_view_s_own_spec_for_another_principal_binds_its_own_arguments(
    owner: User,
) -> None:
    """Nor does that call bind the edge's body: it validates the arguments its
    caller handed it, never the client's request body."""
    _SAME_SEEN.clear()
    User.objects.create(username="other")

    assert _create(_SAME, {"title": "outer"}, owner).status_code == 204
    assert [title for title, _, _ in _SAME_SEEN] == ["outer", "inner"]


_ANOTHER_READING_ITS_CALLER = ServiceSpec(
    service=lambda *, title: None,
    permissions=_OPEN,
    validator=SerializerValidator(_ReadsItsCaller),
    atomic=False,
)


def _dispatches_another_for_its_own_principal(*, title: str, user: Any) -> None:
    dispatch(_ANOTHER_READING_ITS_CALLER, principal=user, arguments={"title": "inner"})


def test_a_kernel_call_of_another_spec_for_the_edge_s_own_principal_reads_none_of_the_edge_s(
    owner: User,
) -> None:
    """The service hands another spec the edge's very principal: that call's
    Validator is not the one the edge dispatched, so it validates its own
    arguments under the offline pair, never the client's body under the view's
    request and view."""
    _SAME_SEEN.clear()
    spec = ServiceSpec(
        service=_dispatches_another_for_its_own_principal,
        permissions=_OPEN,
        validator=SerializerValidator(_ReadsItsCaller),
        atomic=False,
    )

    assert _create(spec, {"title": "outer"}, owner).status_code == 204
    (outer_title, _, outer_view), (inner_title, inner_request, inner_view) = _SAME_SEEN
    assert (outer_title, inner_title) == ("outer", "inner")
    assert isinstance(outer_view, ServiceCreateView)
    assert inner_request.user == owner
    assert not isinstance(inner_view, ServiceCreateView)
