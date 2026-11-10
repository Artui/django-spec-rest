from __future__ import annotations

from typing import Any


def base_serializer_context(*, view: Any, request: Any) -> dict[str, Any]:
    """Build the baseline serializer ``context`` a spec-driven render starts from."""
    getter: Any = getattr(view, "get_serializer_context", None)
    if callable(getter):
        return dict(getter())
    return {"request": request, "format": None, "view": view}


__all__ = ["base_serializer_context"]
