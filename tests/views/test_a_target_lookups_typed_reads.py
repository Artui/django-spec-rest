"""A target lookup's typed reads are coerced and flattened as the spec's own are.

A route capture and a form body carry strings, and a repeated form key carries
every value, so each is read against the type its declaration names: an
integer and a boolean parsed from their string, an array as every value the
key repeats. A JSON body is not flattened, its values are checked as sent, and
a value of either that does not convert is a 400 naming it. A ``reads``
entry on the target lookup is a parameter of the spec, so its type is the one
the value is read against.

The kernel route's answer today, which no plan decision names yet: drfs read a lookup's typed ``QueryParam`` off the query
string. On the kernel route a service spec's arguments are its body and its
declared captures, so the values here are sent there; and a name both the spec
and its lookup read, which drfs gave to the spec, is refused, since a kernel
spec declares one source per name.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceUpdateView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Post
from tests.testapp.serializers import PostSerializer

_factory = APIRequestFactory()

_READS = Parameters(
    (
        Parameter("pk", "integer", required=True),
        Parameter("n", "integer"),
        Parameter("flag", "boolean"),
        Parameter("tags", "array", items="string"),
        Parameter("org", "integer"),
    )
)
_READ = {"n": 3, "flag": True, "tags": ["a", "b"], "org": 7}


class _BodyIn(serializers.Serializer):
    body = serializers.CharField(required=False)


class _UpdateView(ServiceUpdateView):
    permission_classes = []

    def get_permissions(self) -> list[Any]:
        # ``MutationFlowMixin``'s reads a drfs-only field; the spine's views
        # answer the view's own classes the same way.
        return [permission() for permission in self.permission_classes]


def _spec(seen: dict[str, Any], *, lookup_reads: Parameters = _READS, **fields: Any) -> ServiceSpec:
    def selector(
        *, pk: int, n: Any = None, flag: Any = None, tags: Any = None, org: Any = None
    ) -> Any:
        seen.update(n=n, flag=flag, tags=tags, org=org)
        return Post.objects.get(pk=pk)

    def service(*, instance: Any, data: Any) -> Any:
        return instance

    return ServiceSpec(
        service=service,
        validator=SerializerValidator(_BodyIn),
        presenter=SerializerPresenter(PostSerializer),
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE, selector=selector, reads=lookup_reads
        ),
        permissions=(Unrestricted(),),
        atomic=False,
        **fields,
    )


def _put(spec: ServiceSpec, body: Any, fmt: str, **route: Any) -> Any:
    view = type("_View", (_UpdateView,), {"spec": spec}).as_view()
    return view(_factory.put("/", body, format=fmt), **route)


@pytest.mark.django_db
def test_a_form_body_and_a_route_capture_are_read_against_their_types() -> None:
    seen: dict[str, Any] = {}
    post = Post.objects.create(title="a")

    response = _put(
        _spec(seen),
        {"n": "3", "flag": "true", "tags": ["a", "b"]},
        "multipart",
        pk=post.pk,
        org="7",
    )

    assert response.status_code == 200, response.data
    assert seen == _READ


@pytest.mark.django_db
def test_a_json_body_is_read_as_sent_and_a_capture_still_coerced() -> None:
    seen: dict[str, Any] = {}
    post = Post.objects.create(title="a")

    response = _put(
        _spec(seen), {"n": 3, "flag": True, "tags": ["a", "b"]}, "json", pk=str(post.pk), org="7"
    )

    assert response.status_code == 200, response.data
    assert seen == _READ


@pytest.mark.django_db
@pytest.mark.parametrize("fmt", ["json", "multipart"])
def test_a_value_that_does_not_convert_is_refused(fmt: str) -> None:
    seen: dict[str, Any] = {}
    post = Post.objects.create(title="a")

    response = _put(_spec(seen), {"n": "x"}, fmt, pk=post.pk)

    assert response.status_code == 400
    assert "n" in response.data
    assert seen == {}


def test_a_name_the_spec_and_its_lookup_both_read_is_refused() -> None:
    spec_reads = Parameters((Parameter("n", "integer"),))
    lookup_reads = Parameters(
        (Parameter("pk", "integer", required=True), Parameter("n", "integer"))
    )

    with pytest.raises(ImproperlyConfigured, match=r"Parameters \['n'\] are declared by two"):
        _spec({}, lookup_reads=lookup_reads, reads=spec_reads)


def test_a_lookup_read_named_like_a_call_seed_is_refused() -> None:
    lookup_reads = Parameters(
        (Parameter("pk", "integer", required=True), Parameter("request", "string"))
    )

    with pytest.raises(
        ImproperlyConfigured,
        match=r"ServiceSpec\.instance_selector_spec\.reads declares the parameter\(s\) "
        r"\['request'\], which dispatch hands every callable on every mount",
    ):
        _spec({}, lookup_reads=lookup_reads)
