"""The list and retrieve selector Protocols are the kernel's, and type a kernel spec's selector.

The root re-exports them, and a kernel ``SelectorSpec`` takes a callable each one accepts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django_service_specs import SelectorKind, SelectorSpec, Unrestricted
from django_service_specs.selectors.list_selector import ListSelector
from django_service_specs.selectors.list_selector import ListSelector as RootListSelector
from django_service_specs.selectors.retrieve_selector import RetrieveSelector
from django_service_specs.selectors.retrieve_selector import (
    RetrieveSelector as RootRetrieveSelector,
)


@dataclass
class _Author:
    id: int
    name: str


def _list(**kwargs: Any) -> list[_Author]:
    return [_Author(id=1, name="A")]


def _retrieve(*, pk: int, **kwargs: Any) -> _Author | None:
    return _Author(id=pk, name="A")


def test_the_root_s_protocols_are_the_kernel_s() -> None:
    assert RootListSelector is ListSelector
    assert RootRetrieveSelector is RetrieveSelector


def test_a_list_selector_types_a_kernel_spec_s_selector() -> None:
    fn: ListSelector[_Author] = _list
    spec = SelectorSpec(kind=SelectorKind.LIST, selector=fn, permissions=(Unrestricted(),))
    assert spec.selector is _list


def test_a_retrieve_selector_types_a_kernel_spec_s_selector() -> None:
    fn: RetrieveSelector[_Author] = _retrieve
    spec = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=fn, permissions=(Unrestricted(),))
    assert spec.selector is _retrieve
