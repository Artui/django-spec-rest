"""A service parameter named like an input field or a read, and what fills it.

Dispatch hands a service each validated value, and each declared read, by
name. A read the caller may leave out over a keyword with no default is
refused at ``as_view()`` by the kernel's ``check_seeds``, since a call leaving
it out would be refused as missing. Beside a Validator the kernel judges none
of the service's keywords, since a Validator may hand it a value it does not
declare, so such a spec is built and a call is answered by what it sends: a
missing value is a 400 naming it, a sent one is handed over. A parameter with a
default is handed the value the call sends. A selector takes its arguments
from its reads, so a required read is a required argument.

The kernel route's answer today, which no plan decision names yet: a service spec's reads are the body's on the kernel route
(``kernel_arguments``), where drfs read a ``QueryParam`` off the query string,
so each value here is sent in the body.

drfs refused the field case at ``as_view()`` as well, and let a ``kwargs``
provider of any shape waive both; a kernel spec is judged by its provider's
annotated keys instead (``test_spec_validation_e2e``).
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

from django_spec_rest import SelectorListView, ServiceCreateView
from django_spec_rest.service_specs.serializer_validator import SerializerValidator

pytestmark = pytest.mark.django_db

_OPEN = (Unrestricted(),)
_factory = APIRequestFactory()


class _In(serializers.Serializer):
    title = serializers.CharField()


class _CreateView(ServiceCreateView):
    permission_classes = []


def _titled(*, data: Any, title: str) -> dict[str, Any]:
    return {"title": title}


def _titled_or_none(*, data: Any, title: str | None = None) -> dict[str, Any]:
    return {"title": title}


def _scoped(*, data: Any, scope: str) -> dict[str, Any]:
    return {"scope": scope}


def _scoped_or_none(*, data: Any, scope: str | None = None) -> dict[str, Any]:
    return {"scope": scope}


_READ = Parameters((Parameter("scope", "string"),))


def _spec(service: Any, *, validated: bool = True, reads: Parameters = _READ) -> ServiceSpec:
    return ServiceSpec(
        service=service,
        permissions=_OPEN,
        reads=reads,
        validator=SerializerValidator(_In) if validated else None,
        atomic=False,
    )


def _post(spec: ServiceSpec, body: dict[str, Any]) -> Any:
    view = type("_View", (_CreateView,), {"spec": spec}).as_view()
    return view(_factory.post("/", body, format="json"))


def test_an_optional_read_over_a_keyword_with_no_default_is_refused_at_as_view() -> None:
    with pytest.raises(
        ImproperlyConfigured,
        match=r"ServiceSpec\.service requires the keyword\(s\) \['scope'\], declared as "
        r"optional reads that nothing else fills",
    ):
        type("_View", (_CreateView,), {"spec": _spec(_scoped, validated=False)}).as_view()


@pytest.mark.parametrize(
    ("service", "body", "expected"),
    [
        (_titled, {"title": "a", "scope": "s"}, {"title": "a"}),
        (_scoped, {"title": "a", "scope": "s"}, {"scope": "s"}),
    ],
    ids=["field", "read"],
)
def test_beside_a_validator_a_sent_value_is_handed_over(
    service: Any, body: dict[str, Any], expected: dict[str, Any]
) -> None:
    response = _post(_spec(service), body)

    assert response.status_code == 201, response.data
    assert response.data == expected


def test_beside_a_validator_a_read_left_out_is_refused_as_missing() -> None:
    response = _post(_spec(_scoped), {"title": "a"})

    assert response.status_code == 400
    assert "scope" in response.data


@pytest.mark.parametrize(
    ("service", "validated", "expected"),
    [
        (_titled_or_none, True, {"title": "a"}),
        (_scoped_or_none, True, {"scope": "s"}),
        (_scoped_or_none, False, {"scope": "s"}),
    ],
    ids=["field", "read", "read-with-no-validator"],
)
def test_with_a_default_it_is_handed_the_value_over_http(
    service: Any, validated: bool, expected: dict[str, Any]
) -> None:
    body = {"title": "a", "scope": "s"} if validated else {"scope": "s"}

    response = _post(_spec(service, validated=validated), body)

    assert response.status_code == 201, response.data
    assert response.data == expected


def _listed(*, scope: str) -> list[Any]:
    return [{"title": scope}]


@pytest.mark.parametrize(("query", "status"), [("?scope=s", 200), ("", 400)])
def test_a_selectors_required_read_is_a_required_argument(query: str, status: int) -> None:
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=_listed,
        reads=Parameters((Parameter("scope", "string", required=True),)),
        permissions=_OPEN,
    )
    view = type(
        "_View",
        (SelectorListView,),
        {"spec": spec, "serializer_class": _In, "permission_classes": []},
    )

    response = view.as_view()(_factory.get(f"/{query}"))

    assert response.status_code == status
    assert (response.data == [{"title": "s"}]) if status == 200 else ("scope" in response.data)
