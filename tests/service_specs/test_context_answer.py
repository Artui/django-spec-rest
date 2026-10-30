"""``context_answer`` asks a spec's context callable once per question in a call."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from django_spec_rest.service_specs.utils import EDGE_CALL, EdgeCallState, context_answer


@pytest.fixture(autouse=True)
def _in_a_call() -> Iterator[None]:
    token = EDGE_CALL.set(EdgeCallState())
    try:
        yield
    finally:
        EDGE_CALL.reset(token)


def test_a_context_answer_is_held_for_the_names_its_objects_came_under() -> None:
    """The same object under another name is another question, asked afresh."""
    shared = object()
    asked: list[str] = []

    def provider(**handed: Any) -> dict[str, Any]:
        asked.extend(handed)
        return dict(handed)

    first = context_answer(provider, {"scope": shared})
    again = context_answer(provider, {"scope": shared})
    other = context_answer(provider, {"owner": shared})

    assert again is first
    assert other == {"owner": shared}
    assert asked == ["scope", "owner"]
