"""Resolve the active spec for an inspected view, at schema-generation time.

One resolver per spec kind, all walking the same three view shapes:
standalone view, ``@*_action``-decorated handler, viewset ``action_specs``
entry.
"""

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
    """Return the ``ServiceSpec`` driving ``view``'s current request, if any.

    Checked in order: ``view.spec`` on a standalone view, the ``_service_spec``
    stamp on a ``@service_action`` handler, then the ``action_specs`` entry for
    ``view.action``. The last follows the same ``"partial_update"`` →
    ``"update"`` fallback as runtime dispatch, so the documented PATCH schema
    matches what actually validates. ``None`` when no service-style spec
    applies, a ``DiscriminatedAction`` included: that is not a spec, and is
    read through ``resolve_discriminated_action``.
    """
    return _served(view, KernelServiceSpec, "_service_spec")


def resolve_discriminated_action(view: Any) -> DiscriminatedAction | None:
    """Return the ``DiscriminatedAction`` serving ``view``'s current request, if any.

    The twin of ``resolve_service_spec`` over the same surfaces, answering the
    wrapper where a spec would be: its variants are ``.specs``. Never asked of
    a standalone view's ``spec``, which ``as_view()`` refuses it as, though the
    walk reads that surface too.
    """
    return _served(view, DiscriminatedAction, "_service_spec")


def resolve_selector_spec(view: Any) -> KernelSelectorSpec | None:
    """Return the ``SelectorSpec`` driving ``view``'s current read, if any.

    The read-side twin of ``resolve_service_spec``, walking the same three
    surfaces with ``_selector_spec`` as the handler stamp. The ``action_specs``
    lookup is non-raising plus an ``isinstance`` gate, so a write action whose
    entry is a ``ServiceSpec`` yields ``None`` rather than raising during schema
    generation.
    """
    return _served(view, KernelSelectorSpec, "_selector_spec")


def _served(view: Any, kind: type[_Served], stamp: str) -> _Served | None:
    """What ``view`` serves that is a ``kind``: its ``spec``, its handler's ``stamp``, or its ``action_specs`` entry."""
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
