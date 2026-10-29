"""A kernel service spec with no Validator takes no client value for its service's own keywords.

A kernel spec's arguments are what it declares: its Validator's fields, its
target lookup's reads and its own ``reads``. A service keyword none of those
names is the author's to fill - a view's ``get_service_kwargs``, the spec's
``kwargs`` provider, a default - so ``DELETE {"hard": true}`` cannot set
``hard=True`` and a create body cannot set ``is_admin``. A client's key
naming no argument is the unknown-argument policy's: refused under
``REJECT``, dropped under ``IGNORE``, and in neither case handed on.
"""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    UnknownArguments,
    Unrestricted,
)
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView, ServiceDeleteView
from django_spec_rest.dispatch import kernel_edge
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_AUTHOR = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
    permissions=_OPEN,
)
_POLICIES = pytest.mark.parametrize("policy", [UnknownArguments.REJECT, UnknownArguments.IGNORE])


def _delete_view(seen: dict[str, Any], **attrs: Any) -> Any:
    def destroy(*, instance: Author, hard: bool = False) -> None:
        seen["hard"] = hard

    spec = ServiceSpec(
        service=destroy, permissions=_OPEN, instance_selector_spec=_AUTHOR, atomic=False
    )
    return type("_View", (ServiceDeleteView,), {"spec": spec, **attrs}).as_view()


@_POLICIES
def test_a_delete_body_cannot_set_a_service_keyword(
    monkeypatch: pytest.MonkeyPatch, policy: UnknownArguments
) -> None:
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", policy)
    seen: dict[str, Any] = {}
    author = Author.objects.create(name="Kept")
    request = factory.delete("/", {"hard": True}, format="json")
    response = _delete_view(seen)(request, pk=author.pk)
    if policy is UnknownArguments.REJECT:
        assert response.status_code == 400
        assert "Unknown argument." in str(response.data["hard"])
        assert seen == {}
    else:
        assert response.status_code == 204
        assert seen == {"hard": False}


@_POLICIES
def test_a_create_body_cannot_set_a_service_keyword(
    monkeypatch: pytest.MonkeyPatch, policy: UnknownArguments
) -> None:
    monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", policy)
    seen: dict[str, Any] = {}

    def create(*, is_admin: bool = False) -> None:
        seen["is_admin"] = is_admin

    spec = ServiceSpec(service=create, permissions=_OPEN, atomic=False)
    view = type("_View", (ServiceCreateView,), {"spec": spec}).as_view()
    response = view(factory.post("/", {"is_admin": True}, format="json"))
    if policy is UnknownArguments.REJECT:
        assert response.status_code == 400
        assert "Unknown argument." in str(response.data["is_admin"])
        assert seen == {}
    else:
        assert response.status_code == 204
        assert seen == {"is_admin": False}


def test_the_author_s_value_still_fills_a_service_keyword() -> None:
    seen: dict[str, Any] = {}
    author = Author.objects.create(name="Gone")
    view = _delete_view(seen, get_service_kwargs=lambda self: {"hard": True})
    assert view(factory.delete("/"), pk=author.pk).status_code == 204
    assert seen == {"hard": True}
