"""``arender_for_audience`` — async sibling of
[`render_for_audience`][django_spec_rest.dispatch.render_for_audience.render_for_audience]."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_spec_rest.dispatch.render_for_audience import render_for_audience
from django_spec_rest.dispatch.utils import arun_off_loop
from django_spec_rest.types.audience_projection import AudienceProjection
from django_spec_rest.types.selector_spec import SelectorSpec
from django_spec_rest.types.service_spec import ServiceSpec
from django_spec_rest.types.view_hooks import ViewHooks


async def arender_for_audience(
    spec: ServiceSpec[Any, Any, Any] | SelectorSpec[Any, Any],
    value: Any,
    *,
    projection: AudienceProjection | None = None,
    many: bool = False,
    view: Any = None,
    request: Any = None,
    extras: Mapping[str, Any] | None = None,
    view_hooks: ViewHooks | None = None,
    call_context: dict[str, Any] | None = None,
) -> Any:
    """Async
    [`render_for_audience`][django_spec_rest.dispatch.render_for_audience.render_for_audience].

    Identical arguments, identical result. The whole render — and the projection
    that follows it — runs in Django's thread-sensitive executor, for the same
    reason
    [`arender_spec_output`][django_spec_rest.dispatch.arender_spec_output.arender_spec_output]
    exists: rendering evaluates querysets and traverses relations, so an async
    caller cannot do it inline without ``SynchronousOnlyOperation``.
    """
    return await arun_off_loop(
        render_for_audience,
        spec,
        value,
        projection=projection,
        many=many,
        view=view,
        request=request,
        extras=extras,
        view_hooks=view_hooks,
        call_context=call_context,
    )
