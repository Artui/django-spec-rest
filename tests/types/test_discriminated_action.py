"""``DiscriminatedAction`` is no kernel spec: asked to compile, it says so and names its variants."""

from __future__ import annotations

import dataclasses

import pytest
from django_service_specs import ServiceSpec, Unrestricted
from django_service_specs.specs.kernel_spec import kernel_spec

from django_spec_rest.types.discriminated_action import DiscriminatedAction

_SPEC = ServiceSpec(service=lambda: None, permissions=(Unrestricted(),))


def _action() -> DiscriminatedAction:
    return DiscriminatedAction(lambda: "b", {"b": _SPEC, "a": _SPEC})


def test_as_kernel_spec_raises_naming_the_variants() -> None:
    with pytest.raises(TypeError, match=r"\['a', 'b'\]"):
        _action().as_kernel_spec()


def test_the_kernel_refuses_it_as_a_spec() -> None:
    with pytest.raises(TypeError, match="not a kernel spec"):
        kernel_spec(_action())


def test_it_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _action().specs = {}  # ty: ignore[invalid-assignment]


def test_it_holds_what_it_was_handed_by_position() -> None:
    def choose() -> str:
        return "a"

    specs = {"a": _SPEC}
    action = DiscriminatedAction(choose, specs)
    assert (action.discriminator, action.specs) == (choose, specs)
