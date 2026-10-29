"""A server value for a ``ModelSerializer`` field is validated as the field validates it.

A related field takes a primary key, not the row, and hands the service the
row; a value its validators refuse is a 400 for the client; and a read-only
field validates nothing, so a value for it reaches the service parameter as
given.

On the kernel route the seat that fills a Validator field is ``input_data``,
the spec's and beneath it the view's ``get_input_data``, so the validating
cases are given there. ``kwargs`` fills the pool: its value reaches the
service parameter as given, never through the field, which is what a
read-only field's case asks of it. The drfs path validated a
``get_service_kwargs`` value naming a field as well; on the kernel route that
value is the pool's. The view's hooks reach the kernel call, so each case is given
through the spec and through the view.
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


def _view(
    seen: dict[str, Any], *, input_data: Any = None, kwargs: Any = None, hooks: Any = None
) -> type[ServiceCreateView]:
    spec = ServiceSpec(
        service=_service(seen),
        permissions=(Unrestricted(),),
        validator=SerializerValidator(_PostIn),
        input_data=input_data,
        kwargs=kwargs,
        atomic=False,
    )
    return type("_View", (_KernelCreateView,), {"spec": spec, **(hooks or {})})


def _validated_by_the_spec(seen: dict[str, Any], values: dict[str, Any]) -> Any:
    """The spec's ``input_data``, the seat that fills a Validator field."""
    return _view(seen, input_data=lambda: values)


def _validated_by_the_view(seen: dict[str, Any], values: dict[str, Any]) -> Any:
    """The view's ``get_input_data``, the hook layered beneath the spec's ``input_data``."""
    return _view(seen, hooks={"get_input_data": lambda self: values})


def _given_by_the_spec(seen: dict[str, Any], values: dict[str, Any]) -> Any:
    """The spec's ``kwargs``, which fills the pool, not a Validator field."""
    return _view(seen, kwargs=lambda: values)


def _given_by_the_view(seen: dict[str, Any], values: dict[str, Any]) -> Any:
    """The view's ``get_service_kwargs``, the hook layered beneath the spec's ``kwargs``."""
    return _view(seen, hooks={"get_service_kwargs": lambda self: values})


_BY = pytest.mark.parametrize(
    "given",
    [_validated_by_the_spec, _validated_by_the_view],
    ids=["spec-input-data", "view-get-input-data"],
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
    [_given_by_the_spec, _given_by_the_view],
    ids=["spec-kwargs", "view-get-service-kwargs"],
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
