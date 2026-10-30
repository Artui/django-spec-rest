"""A nested selector's ``progress_reporter`` is refused before any view is built.

Only the spec being dispatched runs, so only its ``progress_reporter`` reports.
drfs refused one declared on a nested selector at ``as_view()``; the kernel
refuses it when the spec is built, in the same words for each nested role, so a
view is never handed such a spec.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import SelectorKind, SelectorSpec, ServiceSpec, Unrestricted


def _progress() -> None:
    return None


def _nested(kind: SelectorKind) -> SelectorSpec:
    return SelectorSpec(kind=kind, selector=lambda: None, progress_reporter=_progress)


@pytest.mark.parametrize(
    ("role", "kind"),
    [
        ("output", SelectorKind.RETRIEVE),
        ("instance", SelectorKind.RETRIEVE),
        ("collection", SelectorKind.LIST),
    ],
)
def test_it_is_refused_when_the_spec_is_built(role: str, kind: SelectorKind) -> None:
    nested: dict[str, Any] = {f"{role}_selector_spec": _nested(kind)}

    with pytest.raises(
        ImproperlyConfigured,
        match=rf"ServiceSpec\.{role}_selector_spec declares a progress_reporter, which is "
        r"never run on a nested selector\. Declare it on this ServiceSpec",
    ):
        ServiceSpec(service=lambda **_: None, permissions=(Unrestricted(),), **nested)


def test_the_dispatching_spec_s_own_is_kept() -> None:
    spec = ServiceSpec(
        service=lambda **_: None, permissions=(Unrestricted(),), progress_reporter=_progress
    )

    assert spec.progress_reporter is _progress
