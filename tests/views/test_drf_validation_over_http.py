"""Over HTTP, a lenient ``SerializerValidator`` answers a view's input as DRF's serializer does.

The kernel checks a call's arguments against the Parameters a spec declares
before its Validator runs, which is right for a caller that sends typed JSON
and wrong for a browser or a form: DRF's fields take ``"true"`` and ``1`` for a
boolean, ``123`` for a string, an HTML checkbox's ``"on"``, an empty string for
an optional field in a form, and an unchecked box's absence as ``False``, and
DRF answers every field's refusal at once in its own words. A kernel spec
whose Validator is ``SerializerValidator(..., lenient=True)`` declares each
field by name alone, so the kernel's check passes every value through and the
serializer answers it; each expectation here is what a bare DRF serializer
answers for the same body, on whichever DRF is installed.

A Validator that is not lenient holds the body to its declared types, as every
typed transport does: a JSON ``"true"`` is a string there.
"""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import ServiceSpec, Unrestricted
from rest_framework import serializers
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView
from django_spec_rest.service_specs.serializer_validator import SerializerValidator

_factory = APIRequestFactory()
SEEN: dict[str, Any] = {}
_OPEN = (Unrestricted(),)


class _Lenient(serializers.Serializer):
    title = serializers.CharField(max_length=5, required=False)
    views = serializers.IntegerField(required=False)
    published = serializers.BooleanField(required=False)
    tags = serializers.ListField(child=serializers.IntegerField(), required=False)
    nick = serializers.CharField(required=False, allow_null=True)


class _Checkbox(serializers.Serializer):
    title = serializers.CharField()
    published = serializers.BooleanField()


def _echo(*, data: Any) -> None:
    SEEN["data"] = dict(data)


def _rows(*, data: Any) -> None:
    SEEN["data"] = [dict(row) for row in data]


def _view(serializer: type, *, lenient: bool = True, **spec: Any) -> Any:
    """A create view over a kernel spec; ``get_permissions`` answers the view's own,
    none, as the spine's views do: ``MutationFlowMixin``'s reads a drfs-only field."""
    served = ServiceSpec(
        service=_rows if spec.get("many") else _echo,
        permissions=_OPEN,
        validator=SerializerValidator(serializer, lenient=lenient),
        atomic=False,
        **spec,
    )
    return type(
        "_View",
        (ServiceCreateView,),
        {
            "spec": served,
            "permission_classes": [],
            "authentication_classes": [],
            "get_permissions": lambda self: [],
        },
    ).as_view()


@pytest.fixture(autouse=True)
def _reset() -> None:
    SEEN.clear()


def _request(body: Any, fmt: str | None) -> Any:
    return _factory.post("/", body, format=fmt) if fmt else _factory.post("/", body)


def _drf_answer(serializer: type[Any], body: Any, fmt: str | None, **kwargs: Any) -> Any:
    """What a bare DRF serializer answers for the body the same request parses to."""
    parsed = Request(
        _request(body, fmt), parsers=[JSONParser(), FormParser(), MultiPartParser()]
    ).data
    bound = serializer(data=parsed, **kwargs)
    if not bound.is_valid():
        return bound.errors
    data = bound.validated_data
    return [dict(row) for row in data] if isinstance(data, list) else dict(data)


_JSON_ACCEPTED = {
    "bool-from-true-string": {"published": "true"},
    "bool-from-1-string": {"published": "1"},
    "bool-from-1": {"published": 1},
    "bool-from-on": {"published": "on"},
    "char-from-int": {"title": 123},
    "int-from-string": {"views": "5"},
}


@pytest.mark.parametrize("body", _JSON_ACCEPTED.values(), ids=_JSON_ACCEPTED.keys())
def test_json_drf_accepts_is_accepted(body: dict[str, Any]) -> None:
    response = _view(_Lenient)(_request(body, "json"))

    assert response.status_code == 204, response.data
    assert SEEN["data"] == _drf_answer(_Lenient, body, "json")


_JSON_REFUSED = {
    # Every field's refusal at once: a type refusal hides no other field's.
    "two-fields": {"title": "toolong", "views": "x"},
    "null": {"title": None},
    "not-a-list": {"tags": 1},
    "not-a-string": {"title": True},
}


@pytest.mark.parametrize("body", _JSON_REFUSED.values(), ids=_JSON_REFUSED.keys())
def test_json_drf_refuses_is_refused_in_drfs_words(body: dict[str, Any]) -> None:
    response = _view(_Lenient)(_request(body, "json"))

    assert response.status_code == 400
    assert response.data == _drf_answer(_Lenient, body, "json")


def test_both_fields_refusals_are_answered_together() -> None:
    """Pinned outright, so the comparison above cannot agree with a lost refusal."""
    response = _view(_Lenient)(_request({"title": "toolong", "views": "x"}, "json"))

    assert set(response.data) == {"title", "views"}


# The kernel route reads a form body through ``flat_arguments`` and binds the
# serializer to the plain dict that makes, so DRF's HTML-input reading, which
# keys off a ``QueryDict`` (``html.is_html_input``), never runs: an empty
# optional field is refused rather than absent or ``None``, and an unchecked
# box is missing rather than ``False``.
_HTML_INPUT = pytest.mark.xfail(
    strict=True,
    reason=(
        "the kernel route binds a SerializerValidator to the flat dict flat_arguments "
        "reads off a form body rather than the request's QueryDict, so DRF's HTML-input "
        "reading (an empty optional field, an unchecked checkbox) never runs"
    ),
)

_FORMS = {
    "checkbox-on": ({"published": "on"}, "multipart"),
    "checkbox-yes": ({"published": "yes"}, "multipart"),
    "empty-optional-int": pytest.param({"views": ""}, "multipart", marks=_HTML_INPUT),
    "empty-optional-nullable": pytest.param({"nick": ""}, "multipart", marks=_HTML_INPUT),
    "absent-checkbox": pytest.param({"views": "5"}, "multipart", marks=_HTML_INPUT),
    "form-encoded-checkbox": ({"published": "on"}, None),
    "repeated-key": ({"tags": ["1", "2"]}, None),
}


@pytest.mark.parametrize(("body", "fmt"), _FORMS.values(), ids=_FORMS.keys())
def test_a_form_body_is_read_as_html_input(body: dict[str, Any], fmt: str | None) -> None:
    response = _view(_Lenient)(_request(body, fmt))

    assert response.status_code == 204, response.data
    assert SEEN["data"] == _drf_answer(_Lenient, body, fmt)


@_HTML_INPUT
def test_an_unchecked_required_checkbox_is_false() -> None:
    """A form leaves an unchecked box out, and DRF reads that absence as ``False``."""
    response = _view(_Checkbox)(_request({"title": "t"}, "multipart"))

    assert response.status_code == 204, response.data
    assert SEEN["data"] == {"title": "t", "published": False}


def test_a_bulk_row_is_read_as_drf_reads_it() -> None:
    body = [{"published": "true", "title": 123}]
    response = _view(_Lenient, many=True)(_request(body, "json"))

    # The service presents nothing, which a kernel spec's view answers ``204``.
    assert response.status_code == 204, response.data
    assert SEEN["data"] == _drf_answer(_Lenient, body, "json", many=True)


def test_a_bulk_row_refusal_is_drfs_own() -> None:
    """A list body is the shape DRF takes, so its rows are refused as they always were."""
    response = _view(_Lenient, many=True)(_request([{"views": "x"}], "json"))

    assert response.status_code == 400
    assert "A valid integer is required." in str(response.data)


@pytest.mark.parametrize("body", [[{"title": "ok"}], "x"], ids=["list", "string"])
def test_a_single_call_body_that_is_no_object_is_refused(body: Any) -> None:
    """Changed by design: the edge refuses a body that is no object as a whole,
    a ``400`` in the kernel's words, before any serializer is asked."""
    response = _view(_Lenient)(_request(body, "json"))

    assert response.status_code == 400
    assert "The body must be an object" in str(response.data)
    assert "data" not in SEEN


def test_a_validator_that_is_not_lenient_keeps_the_kernel_s_typed_check() -> None:
    """A typed caller is held to the declared types, as on every typed transport."""
    response = _view(_Lenient, lenient=False)(_request({"published": "true", "views": "x"}, "json"))

    assert response.status_code == 400
    assert response.data == {
        "published": ["Expected a boolean."],
        "views": ["Expected an integer."],
    }
    assert "data" not in SEEN


@pytest.mark.parametrize(
    ("body", "answer"),
    [
        pytest.param({"title": "ok"}, ("Expected an array.", "not_a_list"), id="object"),
        pytest.param({}, ("Expected an array.", "not_a_list"), id="empty"),
        pytest.param(None, ("This field cannot be null.", "null"), id="null"),
    ],
)
def test_a_bulk_body_that_is_no_list_is_refused_under_the_many_argument(
    body: Any, answer: tuple[str, str]
) -> None:
    """Changed by design: the edge hands a ``many`` spec's body to the kernel under
    its ``many_argument`` as sent, so the kernel's shape check refuses it there, in
    its words and with DRF's code, where drfs answered DRF's list serializer's
    ``non_field_errors``."""
    request = (
        _factory.generic("POST", "/", "null", content_type="application/json")
        if body is None
        else _request(body, "json")
    )

    response = _view(_Lenient, many=True)(request)

    assert response.status_code == 400
    (message,) = response.data["items"]
    assert (str(message), message.code) == answer
    assert "data" not in SEEN
