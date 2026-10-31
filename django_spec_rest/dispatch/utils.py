"""Helpers shared by the kernel edge and the views that sit on it."""

from __future__ import annotations

from typing import Any


def fill_call_context(
    call_context: dict[str, Any] | None, *, request: Any, view: Any
) -> dict[str, Any]:
    """The call's context, its four standard entries filled where it has none.

    A live view builds the one dict of its request with this
    (``view_call_context``), and the kernel edge hands that dict to ``dispatch``
    as the call's ``call_context``.
    """
    # The caller's dict itself, tested ``is None`` rather than for truth, so an
    # empty one passed is still theirs. The four standard entries are set where
    # the caller put none, so the caller's win: ``view_call_context`` puts the
    # route's ``format`` first. ``action`` is the operation's name where the view
    # handed in carries one, an empty one being none
    # (test_the_action_is_the_view_s_where_it_has_one).
    context: dict[str, Any] = {} if call_context is None else call_context
    context.setdefault("request", request)
    context.setdefault("view", view)
    context.setdefault("format", None)
    context.setdefault("action", getattr(view, "action", None) or None)
    return context
