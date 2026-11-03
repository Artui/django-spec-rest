"""Mounting a view makes no class: ``as_view()``'s checks read the author's class through.

A project's ``__init_subclass__``, metaclass or subclass registry sees every
class made from its views. ``as_view()`` asks its checks of the view as its
instances will answer, keywords included, and once asked that of a subclass
made per mount, one per ``action_specs`` entry on a viewset, each named like
the author's class: a router mounting one viewset made several. Each test
records every subclass made after the author's class is defined, so each fails
against a tree that makes one.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import SelectorKind, SelectorSpec, ServiceSpec, Unrestricted
from rest_framework.routers import DefaultRouter

from django_spec_rest import ServiceCreateView, ServiceViewSet
from tests.testapp.models import Author

_OPEN = (Unrestricted(),)
_CREATE = ServiceSpec(service=lambda: Author.objects.create(name="Ada"), permissions=_OPEN)
_AUTHORS = SelectorSpec(
    kind=SelectorKind.LIST, selector=lambda: Author.objects.all(), permissions=_OPEN
)

_MADE: list[str] = []


class _Recording:
    """Records every class made from it, as a project's subclass registry would."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _MADE.append(cls.__qualname__)


class _Create(_Recording, ServiceCreateView):
    spec = _CREATE


class _Authors(_Recording, ServiceViewSet):
    action_specs = {"create": _CREATE}


@pytest.fixture(autouse=True)
def _made() -> list[str]:
    _MADE.clear()
    return _MADE


class TestAStandaloneView:
    def test_as_view_makes_no_class(self, _made: list[str]) -> None:
        _Create.as_view()
        assert _made == []

    def test_a_spec_handed_to_as_view_makes_no_class(self, _made: list[str]) -> None:
        _Create.as_view(spec=_CREATE)
        assert _made == []

    def test_a_refusal_of_a_keyword_names_the_author_s_class(self, _made: list[str]) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"^_Create\.spec is a SelectorSpec"):
            _Create.as_view(spec=_AUTHORS)
        assert _made == []


class TestAViewset:
    def test_as_view_with_a_router_s_keywords_makes_no_class(self, _made: list[str]) -> None:
        _Authors.as_view({"post": "create"}, basename="author", detail=False)
        assert _made == []

    def test_a_router_mounting_it_makes_no_class(self, _made: list[str]) -> None:
        router = DefaultRouter()
        router.register("authors", _Authors, basename="author")
        assert router.urls
        assert _made == []

    def test_a_refusal_of_an_entry_names_the_author_s_class_and_the_action(
        self, _made: list[str]
    ) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"^_Authors\.action_specs\['create'\]"):
            _Authors.as_view({"post": "create"}, action_specs={"create": _AUTHORS})
        assert _made == []
