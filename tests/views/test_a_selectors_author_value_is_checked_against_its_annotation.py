"""A selector parameter's value from a route capture is checked; a provider's is not.

Over a live ``SelectorListView``, a route capture of a name the spec reads is
an argument like any a caller sends, so it is checked against the type its read
declares: a value that does not convert is refused with a 400 before the
selector runs, and a string that converts reaches it as the declared type.

Three answers differ from drfs'. Two by design: drfs checked the value
against the selector's annotation, which a kernel spec never reads, since the
signature reflection drops (S3) and its reads declare the type; and it checked
a ``get_selector_kwargs()`` value, which never reaches a kernel spec (the
carry-over list rewrites ``resolve_extra_kwargs`` onto the spec's providers),
so a view overriding the hook beside one is refused when it is built.
The third is the kernel route's answer today, which no plan decision names
yet: drfs checked the spec's ``kwargs`` provider's value too, where the kernel
hands a provider's value to the callable as given.
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
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorListView
from tests.testapp.models import Post

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()
_SEEN: list[Any] = []


class _PostOut(serializers.ModelSerializer):
    class Meta:
        model = Post
        fields = ("id",)


def _selector(*, x: int = 0) -> Any:
    _SEEN.append(x)
    return Post.objects.none()


def _respond(channel: str, value: Any) -> Any:
    """The response of a live list view whose selector's ``x`` comes from ``channel``."""
    fields: dict[str, Any] = {}
    attrs: dict[str, Any] = {}
    route: dict[str, Any] = {}
    if channel == "provider":
        fields["kwargs"] = lambda **_: {"x": value}
    elif channel == "hook":
        attrs["get_selector_kwargs"] = lambda self: {"x": value}
    else:
        route["x"] = value
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=_selector,
        reads=Parameters((Parameter("x", "integer"),)),
        permissions=(Unrestricted(),),
        **fields,
    )
    view = type(
        "View",
        (SelectorListView,),
        {"spec": spec, "serializer_class": _PostOut, "permission_classes": [], **attrs},
    ).as_view()
    _SEEN.clear()
    return view(_factory.get("/"), **route)


def test_a_route_value_that_does_not_convert_is_refused() -> None:
    response = _respond("route", "abc")

    assert response.status_code == 400
    assert list(response.data) == ["x"]
    assert _SEEN == []


def test_a_route_string_that_converts_reaches_the_selector_as_the_declared_type() -> None:
    response = _respond("route", "7")

    assert response.status_code == 200
    assert _SEEN == [7]


@pytest.mark.parametrize("value", ["abc", "7", None])
def test_a_provider_s_value_reaches_the_selector_as_given(value: Any) -> None:
    """Pinned as today's answer, not a decided one: whether a provider's value
    is checked against the read it fills is a question for the owner."""
    response = _respond("provider", value)

    assert response.status_code == 200
    assert [value] == _SEEN


def test_a_view_hook_beside_the_spec_is_refused_when_the_view_is_built() -> None:
    with pytest.raises(ImproperlyConfigured, match="overrides get_selector_kwargs"):
        _respond("hook", "abc")
