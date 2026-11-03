"""A viewset's ``action_specs`` handed to ``as_view()``: checked at mount, as a class attribute is.

A viewset's specs are its ``action_specs``, one per action, which its mixins
read off the instance; so ``as_view(actions, action_specs=...)`` is the
viewset's ``as_view(spec=...)``. A viewset has no ``spec``, so DRF refuses that
keyword itself.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import SelectorKind, SelectorSpec, ServiceSpec, Unrestricted
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorViewSet, ServiceViewSet
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_HOW = pytest.mark.parametrize("how", ["class attribute", "as_view keyword"])


def _mount(base: type, actions: dict[str, str], how: str, **attrs: Any) -> Any:
    if how == "class attribute":
        return type("_ViewSet", (base,), attrs).as_view(actions)
    return type("_ViewSet", (base,), {}).as_view(actions, **attrs)


@_HOW
def test_a_selector_spec_for_a_create_is_refused(how: str) -> None:
    spec = SelectorSpec(kind=SelectorKind.LIST, selector=Author.objects.all, permissions=_OPEN)
    with pytest.raises(
        ImproperlyConfigured, match="is a SelectorSpec, but this view serves a ServiceSpec"
    ):
        _mount(ServiceViewSet, {"post": "create"}, how, action_specs={"create": spec})


@_HOW
def test_a_keyword_nothing_fills_is_refused(how: str) -> None:
    spec = ServiceSpec(service=lambda *, nonsense: None, permissions=_OPEN)
    with pytest.raises(ImproperlyConfigured, match="nonsense"):
        _mount(ServiceViewSet, {"post": "create"}, how, action_specs={"create": spec})


@_HOW
def test_an_update_with_no_target_selector_is_refused(how: str) -> None:
    spec = ServiceSpec(service=lambda: None, permissions=_OPEN)
    with pytest.raises(ImproperlyConfigured, match="declares no target selector"):
        _mount(ServiceViewSet, {"put": "update"}, how, action_specs={"update": spec})


def test_a_keyword_s_specs_are_served() -> None:
    ada = Author.objects.create(name="Ada")
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda: Author.objects.order_by("pk"),
        permissions=_OPEN,
        presenter=SerializerPresenter(AuthorSerializer),
    )
    view = SelectorViewSet.as_view({"get": "list"}, action_specs={"list": spec})
    assert view(factory.get("/")).data == [{"id": ada.pk, "name": "Ada"}]


def test_a_spec_keyword_is_drf_s_own_refusal() -> None:
    """A viewset declares no ``spec``, so DRF refuses the keyword before anything serves."""
    spec = ServiceSpec(service=lambda: None, permissions=_OPEN)
    with pytest.raises(TypeError, match="spec"):
        ServiceViewSet.as_view({"post": "create"}, spec=spec)
