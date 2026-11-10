from __future__ import annotations

from typing import Any, TypeVar

from django_service_specs.specs.selector_spec import SelectorSpec as KernelSelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec as KernelServiceSpec

from django_spec_rest.types.discriminated_action import DiscriminatedAction
from django_spec_rest.viewsets.utils import resolve_action_spec_entry

_Served = TypeVar("_Served")


def resolve_service_spec(
    view: Any,
) -> KernelServiceSpec | None:
    """Return the ``ServiceSpec`` driving ``view``'s current request, if any."""
    return _served(view, KernelServiceSpec, "_service_spec")


def resolve_discriminated_action(view: Any) -> DiscriminatedAction | None:
    """Return the ``DiscriminatedAction`` serving ``view``'s current request, if any."""
    return _served(view, DiscriminatedAction, "_service_spec")


def resolve_selector_spec(view: Any) -> KernelSelectorSpec | None:
    """Return the ``SelectorSpec`` driving ``view``'s current read, if any."""
    return _served(view, KernelSelectorSpec, "_selector_spec")


def _served(view: Any, kind: type[_Served], stamp: str) -> _Served | None:
    """What ``view`` serves as a ``kind``: its ``spec``, its ``stamp``, or ``action_specs``."""
    spec = getattr(view, "spec", None)
    if isinstance(spec, kind):
        return spec

    action_name = getattr(view, "action", None)
    if action_name is None:
        return None

    handler = getattr(view, action_name, None)
    action_spec = getattr(handler, stamp, None)
    if isinstance(action_spec, kind):
        return action_spec

    action_specs = getattr(view, "action_specs", None)
    if action_specs is not None:
        entry = resolve_action_spec_entry(action_specs, action_name)
        if isinstance(entry, kind):
            return entry
    return None
