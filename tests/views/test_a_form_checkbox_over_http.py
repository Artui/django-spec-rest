"""A checked box sends ``on``; a kernel ``FormValidator`` over a form body reads it as ``True``.

``coerce_flat`` spells a boolean as ``true``, ``false``, ``1`` or ``0`` alone, so
without the edge's reading a form body's ``on`` for a parameter declared
``boolean`` (a ``forms.BooleanField``, or the ``<name>-clear`` a file field's
clearable input declares) is refused. The reading is a form body's alone: a
query string and a JSON body keep the kernel's four spellings. A
``SerializerValidator`` declares each form field ``any`` and so never meets it.
Every case drives a real view.
"""

from __future__ import annotations

from typing import Any

import pytest
from django import forms
from django.db.models import QuerySet
from django_service_specs import (
    FormValidator,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorListView, ServiceCreateView, ServiceUpdateView
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_SEEN: dict[str, Any] = {}


class _Form(forms.Form):
    published = forms.BooleanField(required=False)
    title = forms.CharField(required=False)
    picks = forms.MultipleChoiceField(choices=[("on", "On"), ("off", "Off")], required=False)
    marks = forms.TypedMultipleChoiceField(
        choices=[(True, "yes"), (False, "no")], coerce=lambda v: v in (True, "True"), required=False
    )


def _service(*, data: Any) -> None:
    _SEEN.clear()
    _SEEN.update(data)


def _view() -> Any:
    spec = ServiceSpec(service=_service, validator=FormValidator(_Form), permissions=_OPEN)
    return ServiceCreateView.as_view(spec=spec)


def _post(body: Any, fmt: str | None = "multipart", path: str = "/") -> Any:
    if fmt is None:
        return _view()(_factory.post(path, body, content_type="application/x-www-form-urlencoded"))
    return _view()(_factory.post(path, body, format=fmt))


@pytest.mark.parametrize("fmt", ["multipart", None], ids=["multipart", "urlencoded"])
def test_a_boolean_field_posted_as_on_arrives_as_true(fmt: str | None) -> None:
    """Fails with ``Enter true, false, 1 or 0.`` on the field, without ``_checked_boxes``' arm."""
    response = _post({"published": "on"} if fmt else "published=on", fmt)

    assert response.status_code == 204, response.data
    assert _SEEN["published"] is True


def test_a_boolean_field_still_reads_the_kernel_s_spellings_in_a_form_body() -> None:
    """``false`` stays ``False``: the reading adds ``on`` and takes nothing away."""
    response = _post({"published": "false"})

    assert response.status_code == 204, response.data
    assert _SEEN["published"] is False


def test_no_other_truthy_string_is_a_boolean_in_a_form_body() -> None:
    """``yes`` is not widened to: it is refused by name, as ever."""
    response = _post({"published": "yes"})

    assert response.status_code == 400
    assert list(response.data) == ["published"]


def test_an_array_of_booleans_reads_each_on() -> None:
    """Fails with the element at index 0 refused, without ``_checked_boxes``'s array arm."""
    response = _post({"marks": ["on", "false"]})

    assert response.status_code == 204, response.data
    assert _SEEN["marks"] == [True, False]


def test_a_string_field_keeps_a_value_of_on() -> None:
    """Fails with the string read as ``True``, were the reading not directed by the declaration."""
    response = _post({"title": "on"})

    assert response.status_code == 204, response.data
    assert _SEEN["title"] == "on"


def test_an_array_of_strings_keeps_a_value_of_on() -> None:
    """Fails with the element read as ``True``, were the array's element type not asked."""
    response = _post({"picks": ["on", "off"]})

    assert response.status_code == 204, response.data
    assert _SEEN["picks"] == ["on", "off"]


def test_an_undeclared_key_is_left_for_the_closed_set() -> None:
    """A key naming no parameter is dropped at the edge as ever, not looked up as a boolean."""
    response = _post({"published": "on", "stray": "on"})

    assert response.status_code == 204, response.data
    assert "stray" not in _SEEN


def test_a_json_body_s_on_is_still_refused() -> None:
    """The client typed a JSON value: ``"on"`` is no boolean there."""
    response = _post({"published": "on"}, "json")

    assert response.status_code == 400
    assert list(response.data) == ["published"]


class _Authors(SelectorListView):
    serializer_class = AuthorSerializer


def _authors(*, published: bool) -> QuerySet[Author]:
    return Author.objects.none()


def test_a_query_string_s_on_is_still_refused() -> None:
    """The query string is a flat wire of its own: ``?published=on`` is refused as before."""
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=_authors,
        reads=Parameters.of(Parameter("published", "boolean", required=True)),
        permissions=_OPEN,
    )
    view = _Authors.as_view(spec=spec)

    refused = view(_factory.get("/", {"published": "on"}))
    assert refused.status_code == 400, refused.data
    assert list(refused.data) == ["published"]
    assert view(_factory.get("/", {"published": "true"})).status_code == 200


def test_a_query_string_s_on_beside_a_form_body_is_still_refused() -> None:
    """Fails with the query string's ``on`` as ``True``, were ``_checked_boxes`` handed the scope.

    ``flag`` is a target read, so the body's own ``flag`` is dropped and the query
    string's is what scopes the call: typed by its client, as it is on a ``GET``.
    """
    _SEEN.clear()
    spec = ServiceSpec(
        service=_service,
        validator=FormValidator(_Form),
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, flag: Author.objects.first(),
            reads=Parameters.of(Parameter("flag", "boolean", required=True)),
        ),
        permissions=_OPEN,
    )
    view = ServiceUpdateView.as_view(spec=spec)

    refused = view(_factory.patch("/?flag=on", {"title": "t"}, format="multipart"), pk=1)
    assert refused.status_code == 400, refused.data
    assert list(refused.data) == ["flag"]
    assert _SEEN == {}
