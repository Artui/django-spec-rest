"""A target lookup's typed reads are coerced and flattened as a query string's are.

A target lookup's reads come from the route's captures and the query string
alone, never the body (``kernel_arguments``), and both carry strings, a
repeated query key carrying every value: so each is read against the type its
declaration names, an integer and a boolean parsed from their string, an array
as every value the key repeats, and a value that does not convert is a 400
naming it. A ``reads`` entry on the target lookup is a parameter of the spec,
so its type is the one the value is read against. A body's value for a read,
typed or not, is no read at all. A name both the spec and its lookup read,
which drfs gave to the spec, is refused, since a kernel spec declares one
source per name.
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


def _put(spec: ServiceSpec, body: Any, fmt: str, url: str = "/", **route: Any) -> Any:
    view = type("_View", (_UpdateView,), {"spec": spec}).as_view()
    return view(_factory.put(url, body, format=fmt), **route)


@pytest.mark.django_db
@pytest.mark.parametrize("fmt", ["json", "multipart"])
def test_a_query_string_and_a_route_capture_are_read_against_their_types(fmt: str) -> None:
    seen: dict[str, Any] = {}
    post = Post.objects.create(title="a")

    response = _put(
        _spec(seen),
        {"body": "x"},
        fmt,
        url="/?n=3&flag=true&tags=a&tags=b",
        pk=str(post.pk),
        org="7",
    )

    assert response.status_code == 200, response.data
    assert seen == _READ


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fmt", "body"),
    [
        ("json", {"n": 3, "flag": True, "tags": ["a", "b"], "org": 7}),
        ("multipart", {"n": "3", "flag": "true", "tags": ["a", "b"], "org": "7"}),
    ],
    ids=["json", "multipart"],
)
def test_a_body_s_value_for_a_read_is_no_read(fmt: str, body: dict[str, Any]) -> None:
    seen: dict[str, Any] = {}
    post = Post.objects.create(title="a")

    response = _put(_spec(seen), body, fmt, pk=post.pk)

    assert response.status_code == 200, response.data
    assert seen == {"n": None, "flag": None, "tags": None, "org": None}


@pytest.mark.django_db
@pytest.mark.parametrize("fmt", ["json", "multipart"])
def test_a_value_that_does_not_convert_is_refused(fmt: str) -> None:
    seen: dict[str, Any] = {}
    post = Post.objects.create(title="a")

    response = _put(_spec(seen), {"body": "x"}, fmt, url="/?n=x", pk=post.pk)

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
