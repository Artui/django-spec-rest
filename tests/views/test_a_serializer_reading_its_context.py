"""A kernel spec's input serializer reading ``self.context`` unguarded, over HTTP.

DRF builds an input serializer with its view's context, so a serializer may
read the request or the view while it is built or while its fields are: a
``PrimaryKeyRelatedField`` scoped to the caller, a field a query value turns
on, a field the route names. A ``SerializerValidator`` describes its
serializer to learn its parameters, and describes it with the call's own
request and view, so each answers as the view always did. The scope holds in
the serializer that validates: a caller picks a row of its own and is refused
another's.

The call's context is DRF's serializer context, one dict per request handed to
every serializer of the call as the very object: the drfs path's
``test_each_serializer_of_the_call_has_its_own_context`` inverts, as
``test_the_call_s_context_is_every_serializer_s_context`` here.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User
from django_service_specs import ServiceSpec, Unrestricted
from rest_framework import serializers
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest import ServiceCreateView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
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
        "The kernel route describes the serializer with no request or view: kernel_arguments "
        "(dispatch/kernel_edge.py) asks spec.parameters() before EDGE_CALL is set and with no "
        "DescribeBinding, so SerializerValidator.parameters() reaches describe_serializer "
        "(service_specs/utils.py) bound with no context, and neither the seat's "
        "serializer_context."
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


@_DESCRIBED_WITH_NO_CALL
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


@_DESCRIBED_WITH_NO_CALL
def test_a_live_view_builds_the_fields_from_its_query_string(owner: User) -> None:
    seen: dict[str, Any] = {}

    response = _create(_spec(_FieldsFromTheQuery, seen), {"extra": "e"}, owner, url="/?extra=1")

    assert response.status_code == 204, response.data
    assert seen == {"data": {"extra": "e"}}


@_DESCRIBED_WITH_NO_CALL
def test_a_live_view_builds_the_fields_from_its_route(owner: User) -> None:
    seen: dict[str, Any] = {}

    response = _create(_spec(_FieldsFromTheView, seen), {"title": "t"}, owner)

    assert response.status_code == 204, response.data
    assert seen == {"data": {"title": "t"}}


@_DESCRIBED_WITH_NO_CALL
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
        "Each serializer is handed its own copy of the context (call_base_context and "
        "base_serializer_context, service_specs/), and the view's call context is built "
        "by fill_call_context rather than as get_serializer_context() answers it "
        "(view_call_context, views/utils.py): the two halves land together."
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
