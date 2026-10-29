"""``acall_selector`` — async counterpart to
[`call_selector`][django_spec_rest.selectors.call_selector.call_selector]."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

from rest_framework.request import Request

from django_spec_rest.is_async import is_async
from django_spec_rest.views.utils import request_seeds, resolve_callable_kwargs

ResultT = TypeVar("ResultT")


async def acall_selector(
    selector: Callable[..., ResultT] | Callable[..., Awaitable[ResultT]],
    *,
    request: Request,
    **extras: Any,
) -> ResultT:
    """Invoke ``selector`` from async code with the framework's kwargs pool.

    Async selectors are awaited; sync selectors are called inline.
    """
    pool: dict[str, Any] = {**request_seeds(request), **extras}
    kwargs = resolve_callable_kwargs(selector, pool)
    if is_async(selector):
        async_selector = cast("Callable[..., Awaitable[ResultT]]", selector)
        return await async_selector(**kwargs)
    sync_selector = cast("Callable[..., ResultT]", selector)
    return sync_selector(**kwargs)
