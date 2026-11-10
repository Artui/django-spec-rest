from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, cast, overload

from django_service_specs.types.is_async import is_async
from typing_extensions import Format, get_annotations

from django_spec_rest.service_specs.translate_drf_refusals import translate_drf_refusals


@overload
def translating_drf_refusals(fn: None) -> None: ...


@overload
def translating_drf_refusals(fn: Callable[..., Any]) -> Callable[..., Any]: ...


def translating_drf_refusals(fn: Callable[..., Any] | None) -> Callable[..., Any] | None:
    """``fn``, its DRF refusals leaving as the kernel's classes; ``None`` for no callable."""
    if fn is None:
        return None
    if is_async(fn):

        async def translating(*args: Any, **kwargs: Any) -> Any:
            with translate_drf_refusals():
                return await fn(*args, **kwargs)
    else:

        def translating(*args: Any, **kwargs: Any) -> Any:
            with translate_drf_refusals():
                return fn(*args, **kwargs)

    translating.__name__ = getattr(fn, "__name__", "callable")
    translating.__qualname__ = getattr(fn, "__qualname__", translating.__name__)
    translating.__module__ = getattr(fn, "__module__", None) or __name__
    if inspect.isfunction(fn) or inspect.ismethod(fn):
        translating.__doc__ = fn.__doc__
        translating.__dict__.update(fn.__dict__)
    translating.__annotations__ = dict(get_annotations(fn, format=Format.FORWARDREF))
    cast(Any, translating).__wrapped__ = fn
    cast(Any, translating).__signature__ = inspect.signature(fn)
    return translating
