"""A kernel spec's view's ``response_finalizer`` across the HTTP flows.

A kernel ``ServiceSpec`` has no ``response_finalizer``, which is HTTP's alone,
so its view declares it (``MutationFlowMixin.response_finalizer``), and off HTTP
there is nothing to skip: no transport but the view reads it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceError,
    ServiceSpec,
    Unrestricted,
)
from django_service_specs.mutations.delete_collection import delete_collection
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView, ServiceDeleteView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author, Post
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _AuthorIn(serializers.Serializer):
    name = serializers.CharField()


def _create_author(*, data: dict[str, Any]) -> Author:
    return Author.objects.create(name=data["name"])


def _set_cookie(*, response: Response) -> None:
    # Returns None, so the same response is kept, now carrying the cookie.
    response.set_cookie("session", "abc")


_CREATE = ServiceSpec(
    service=_create_author,
    permissions=_OPEN,
    validator=SerializerValidator(_AuthorIn),
    presenter=SerializerPresenter(AuthorSerializer),
)


def _view(base: type, spec: ServiceSpec, finalizer: Any) -> Any:
    return type("_View", (base,), {"spec": spec, "response_finalizer": finalizer}).as_view()


class TestResponseFinalizerSingle:
    def test_finalizer_sets_cookie_on_a_presented_body(self) -> None:
        response = _view(ServiceCreateView, _CREATE, _set_cookie)(
            factory.post("/", {"name": "Ada"}, format="json")
        )
        assert response.status_code == 201
        assert response.data["name"] == "Ada"
        assert response.cookies["session"].value == "abc"

    def test_finalizer_applies_on_an_empty_body_and_sees_the_target(self) -> None:
        author = Author.objects.create(name="Gone")
        seen: dict[str, Any] = {}

        def add_header(*, response: Response, instance: Author) -> None:
            seen["instance"] = instance.name
            response["X-Deleted"] = "1"

        spec = ServiceSpec(
            service=lambda *, instance: instance.delete() and None,
            permissions=_OPEN,
            instance_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
                reads=Parameters.of(Parameter("pk", "integer", required=True)),
            ),
        )
        response = _view(ServiceDeleteView, spec, add_header)(factory.delete("/"), pk=author.pk)
        assert response.status_code == 204
        assert response["X-Deleted"] == "1"
        assert seen == {"instance": "Gone"}

    def test_finalizer_can_swap_the_response(self) -> None:
        def swap(*, result: Author, response: Response) -> Response:
            return Response({"id": result.pk, "swapped": True}, status=response.status_code)

        response = _view(ServiceCreateView, _CREATE, swap)(
            factory.post("/", {"name": "Ada"}, format="json")
        )
        assert response.status_code == 201
        assert response.data == {"id": Author.objects.get().pk, "swapped": True}

    def test_result_is_the_service_return_and_data_the_validated_input(self) -> None:
        """A finalizer keying on the service's own return sees what the service
        produced, even where an output selector re-reads a different object."""

        @dataclass
        class _Made:
            author: Author
            created: bool

        seen: dict[str, Any] = {}

        def record(*, result: _Made, data: Any) -> None:
            seen["created"] = result.created
            seen["data"] = dict(data)

        spec = ServiceSpec(
            service=lambda *, data: _Made(Author.objects.create(name=data["name"]), True),
            permissions=_OPEN,
            validator=SerializerValidator(_AuthorIn),
            output_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, result: Author.objects.get(pk=result.author.pk),
                presenter=SerializerPresenter(AuthorSerializer),
            ),
        )
        response = _view(ServiceCreateView, spec, record)(
            factory.post("/", {"name": "Ada"}, format="json")
        )
        assert response.data["name"] == "Ada"
        assert seen == {"created": True, "data": {"name": "Ada"}}

    def test_error_path_bypasses_finalizer(self) -> None:
        called: list[bool] = []

        def boom() -> None:
            raise ServiceError("nope")

        spec = ServiceSpec(service=boom, permissions=_OPEN, atomic=False)
        response = _view(ServiceCreateView, spec, lambda **_: called.append(True))(
            factory.post("/", {}, format="json")
        )
        assert response.status_code == 422
        assert called == []


class TestResponseFinalizerBulk:
    def test_finalizer_on_a_bulk_body(self) -> None:
        def tag_header(*, response: Response, result: Any) -> None:
            response["X-Count"] = str(len(result))

        spec = ServiceSpec(
            service=lambda *, data: [Author.objects.create(name=row["name"]) for row in data],
            permissions=_OPEN,
            validator=SerializerValidator(_AuthorIn),
            presenter=SerializerPresenter(AuthorSerializer),
            many=True,
            atomic=False,
        )
        response = _view(ServiceCreateView, spec, tag_header)(
            factory.post("/", [{"name": "a"}, {"name": "b"}], format="json")
        )
        assert response.status_code == 201
        assert response["X-Count"] == "2"
        assert [row["name"] for row in response.data] == ["a", "b"]

    def test_finalizer_on_a_bulk_empty_body(self) -> None:
        Post.objects.create(title="x")

        def add_header(*, response: Response) -> None:
            response["X-Bulk"] = "done"

        spec = ServiceSpec(
            service=delete_collection(Post),
            permissions=_OPEN,
            collection_selector_spec=SelectorSpec(
                kind=SelectorKind.LIST, selector=lambda: Post.objects.all()
            ),
            atomic=False,
        )
        response = _view(ServiceDeleteView, spec, add_header)(factory.delete("/"))
        assert response.status_code == 204
        assert response["X-Bulk"] == "done"
        assert not Post.objects.exists()


class TestAFinalizerTheViewCannotCall:
    """Refused when the view is built, as a drfs spec's ``response_finalizer``
    is, rather than raising ``TypeError`` once the service has committed."""

    def test_a_finalizer_requiring_a_key_the_framework_lacks_is_refused_at_as_view(
        self,
    ) -> None:
        def finalizer(*, call_context: Any) -> None: ...

        spec = ServiceSpec(service=_create_author, permissions=_OPEN)
        with pytest.raises(ImproperlyConfigured, match=r"\['call_context'\] the framework"):
            _view(ServiceCreateView, spec, finalizer)

    def test_a_finalizer_that_is_no_callable_is_refused_at_as_view(self) -> None:
        spec = ServiceSpec(service=_create_author, permissions=_OPEN)
        with pytest.raises(ImproperlyConfigured, match="`response_finalizer` must be a callable"):
            _view(ServiceCreateView, spec, "finalize")
