from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ViewHooks:
    """The HTTP view's hook-chain contributions, resolved and passed down."""

    # Named for its chain, not for services: the same carrier serves the selector chain.
    extra_kwargs: Mapping[str, Any] | None = None
    input_data: Mapping[str, Any] | None = None
    input_serializer_context: Mapping[str, Any] | None = None
    output_serializer_context: Callable[[Any], Mapping[str, Any]] | None = None
    # The transport-native half of the progress fan-in; the core sees an HTTP view as transport.
    progress: Any | None = None


__all__ = ["ViewHooks"]
