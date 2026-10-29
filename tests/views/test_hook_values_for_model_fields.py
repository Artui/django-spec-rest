"""A server value for a ``ModelSerializer`` field is validated as the field validates it.

A related field takes a primary key, not the row, and hands the service the
row; a value its validators refuse is a 400 for the client; and a read-only
field validates nothing, so a value for it reaches the service parameter as
given. Two places give a kernel spec's call such a value: the spec's own
``kwargs`` provider, and the view's ``get_service_kwargs`` hook. Neither is
validated by the field on the kernel route yet; each is a strict xfail.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django_service_specs import ServiceSpec, Unrestricted
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author, Post

_factory = APIRequestFactory()


class _PostIn(serializers.ModelSerializer):
    class Meta:
        model = Post
        fields = ["title", "author", "views"]
        read_only_fields = ["views"]
        extra_kwargs = {"title": {"max_length": 3}}


def _service(seen: dict[str, Any]) -> Callable[..., None]:
    def service(*, data: Any, author: Any = None, views: Any = None, title: Any = None) -> None:
        seen.update(data=dict(data), author=author, views=views, title=title)

    return service


class _KernelCreateView(ServiceCreateView):
    """``get_permissions`` answers the view's own classes, as for a spec setting none.

    ``MutationFlowMixin.get_permissions`` reads ``spec.permission_classes``,
    which a kernel spec has no attribute for.
    """

    permission_classes: list[Any] = []

    def get_permissions(self) -> list[Any]:
        return [permission() for permission in self.permission_classes]


def _by_the_spec(seen: dict[str, Any], values: dict[str, Any]) -> type[ServiceCreateView]:
    class _View(_KernelCreateView):
        spec = ServiceSpec(
            service=_service(seen),
            permissions=(Unrestricted(),),
            validator=SerializerValidator(_PostIn),
            kwargs=lambda: values,
            atomic=False,
        )

    return _View


def _by_the_view(seen: dict[str, Any], values: dict[str, Any]) -> type[ServiceCreateView]:
    class _View(_KernelCreateView):
        spec = ServiceSpec(
            service=_service(seen),
            permissions=(Unrestricted(),),
            validator=SerializerValidator(_PostIn),
            atomic=False,
        )

        def get_service_kwargs(self) -> dict[str, Any]:
            return values

    return _View


_HOOK_NOT_CARRIED = pytest.mark.xfail(
    strict=True,
    reason=(
        "The view's hook chains reach no kernel call: the kernel branch of "
        "dispatch_mutation_for_spec (views/mutation/utils.py) resolves no resolve_view_hooks, "
        "and dispatch_kernel_spec (dispatch/kernel_edge.py) sets no view_hooks or "
        "author_values on EdgeCallState."
    ),
)

_SPEC_VALUE_NOT_VALIDATED = pytest.mark.xfail(
    strict=True,
    reason=(
        "On the kernel route a kwargs provider's value naming a validator field reaches the "
        "service as given, never validated by the field (no server_values on EdgeCallState, "
        "dispatch/kernel_edge.py): a gap or a decided change, to be settled with the edge's "
        "server values."
    ),
)

_BY = pytest.mark.parametrize(
    "given",
    [
        pytest.param(_by_the_spec, marks=_SPEC_VALUE_NOT_VALIDATED),
        pytest.param(_by_the_view, marks=_HOOK_NOT_CARRIED),
    ],
    ids=["spec-kwargs", "view-hook"],
)


@pytest.mark.django_db
@_BY
def test_a_row_for_a_related_field_is_refused(given: Callable[..., Any]) -> None:
    author = Author.objects.create(name="a")
    seen: dict[str, Any] = {}

    response = given(seen, {"author": author}).as_view()(
        _factory.post("/", {"title": "t"}, format="json")
    )

    assert response.status_code == 400
    assert response.data == {"author": ["Incorrect type. Expected pk value, received Author."]}
    assert seen == {}


@pytest.mark.django_db
@_BY
def test_a_primary_key_for_a_related_field_arrives_as_its_row(given: Callable[..., Any]) -> None:
    author = Author.objects.create(name="a")
    seen: dict[str, Any] = {}

    response = given(seen, {"author": author.pk}).as_view()(
        _factory.post("/", {"title": "t"}, format="json")
    )

    assert response.status_code == 204, response.data
    assert seen["author"] == author
    assert seen["data"] == {"title": "t", "author": author}


@pytest.mark.django_db
@_BY
def test_a_value_the_fields_validators_refuse_is_the_clients_400(given: Callable[..., Any]) -> None:
    seen: dict[str, Any] = {}

    response = given(seen, {"title": "too long"}).as_view()(
        _factory.post("/", {"title": "ok"}, format="json")
    )

    assert response.status_code == 400
    assert response.data == {"title": ["Ensure this field has no more than 3 characters."]}
    assert seen == {}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "given",
    [_by_the_spec, pytest.param(_by_the_view, marks=_HOOK_NOT_CARRIED)],
    ids=["spec-kwargs", "view-hook"],
)
def test_a_value_for_a_read_only_field_reaches_the_parameter_as_given(
    given: Callable[..., Any],
) -> None:
    seen: dict[str, Any] = {}

    response = given(seen, {"views": "42"}).as_view()(
        _factory.post("/", {"title": "t"}, format="json")
    )

    assert response.status_code == 204, response.data
    assert seen["views"] == "42"
    assert seen["data"] == {"title": "t"}
