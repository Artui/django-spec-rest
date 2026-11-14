from __future__ import annotations

import inspect
import io
from collections.abc import Callable, Mapping
from typing import Any

from django.http import FileResponse, HttpResponseBase, StreamingHttpResponse
from django.utils.http import content_disposition_header
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.resolve_callable_kwargs import (
    resolve_callable_kwargs as bind_by_name_only,
)
from django_service_specs.schema.file_output import file_output
from django_service_specs.types.build_call_context import build_call_context
from django_service_specs.types.unset import UNSET
from rest_framework.exceptions import NotAcceptable
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.utils.mediatypes import media_type_matches

from django_spec_rest.types.discriminated_action import DiscriminatedAction
from django_spec_rest.types.rest_transport import REST_TRANSPORT
from django_spec_rest.types.view_hooks import ViewHooks


def resolve_extra_kwargs(
    view: Any,
    request: Request,
    *,
    action_hook: str | None,
    catch_all_hook: str,
) -> dict[str, Any]:
    """Collect the extras that should be merged into a service/selector pool."""
    extras: dict[str, Any] = {}
    context = view_call_context(view, request)
    catch_all = getattr(view, catch_all_hook, None)
    if catch_all is not None:
        extras.update(
            _invoke_provider(catch_all, view=view, request=request, extras={}, call_context=context)
        )
    if action_hook is not None:
        hook = getattr(view, action_hook, None)
        if hook is not None:
            extras.update(
                _invoke_provider(hook, view=view, request=request, extras={}, call_context=context)
            )
    return extras


def resolve_input_extras(
    view: Any,
    request: Request,
    *,
    action_hook: str | None,
    catch_all_hook: str,
    extras: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect the extras to merge into the serializer input dict."""
    payload: Mapping[str, Any] = extras if extras is not None else {}
    collected: dict[str, Any] = {}
    context = view_call_context(view, request)
    catch_all = getattr(view, catch_all_hook, None)
    if catch_all is not None:
        collected.update(
            _invoke_provider(
                catch_all, view=view, request=request, extras=payload, call_context=context
            )
        )
    if action_hook is not None:
        hook = getattr(view, action_hook, None)
        if hook is not None:
            collected.update(
                _invoke_provider(
                    hook, view=view, request=request, extras=payload, call_context=context
                )
            )
    return collected


def view_pool_seeds(view: Any) -> PoolSeeds:
    """The seeds ``view`` resolves its spec's callables with: its ``pool_seeds``."""
    return getattr(view, "pool_seeds", DEFAULT_POOL_SEEDS)


def view_call_context(view: Any, request: Request) -> dict[str, Any]:
    """The call's context of the request ``view`` is serving: one dict per request."""
    context: dict[str, Any] | None = getattr(view, "_call_context", None)
    if context is None:
        context = build_call_context(
            REST_TRANSPORT,
            request=request,
            view=view,
            format=getattr(view, "format_kwarg", None),
            action=getattr(view, "action", None) or None,
        )
        view._call_context = context
    return context


def _invoke_provider(
    fn: Callable[..., Any],
    *,
    view: Any,
    request: Request,
    extras: Mapping[str, Any],
    call_context: dict[str, Any] | None = None,
) -> Any:
    """Call ``fn`` with the subset of ``{view, request, call_context, **extras}`` it declares."""
    pool: dict[str, Any] = {"view": view, "request": request, **extras}
    if call_context is not None:
        pool["call_context"] = call_context
    result: Any = fn(**bind_by_name_only(fn, pool))
    return {key: value for key, value in result.items() if value is not UNSET}


def layer_serializer_context(
    base: Mapping[str, Any],
    view: Any,
    request: Request,
    *,
    direction_hook: str,
    action_hook: str | None,
    extras: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Layer the directional and action context hooks onto ``base``."""
    payload: Mapping[str, Any] = extras if extras is not None else {}
    call: dict[str, Any] = view_call_context(view, request)
    context: dict[str, Any] = dict(base)
    direction = getattr(view, direction_hook, None)
    if direction is not None:
        context.update(
            _invoke_provider(
                direction, view=view, request=request, extras=payload, call_context=call
            )
        )
    if action_hook is not None:
        hook = getattr(view, action_hook, None)
        if hook is not None:
            context.update(
                _invoke_provider(
                    hook, view=view, request=request, extras=payload, call_context=call
                )
            )
    return context


def get_class_attr(view: Any, name: str) -> Any:
    """Return the named attribute as the view was configured, without instance binding."""
    configured = vars(view)
    return configured[name] if name in configured else getattr(type(view), name, None)


def action_answer(view: Any, name: str) -> Any:
    """The view's ``success_status`` or ``response_finalizer`` (``name``) for its action."""
    action = getattr(view, "action", None)
    if isinstance(action, str):
        stamped = getattr(getattr(view, action, None), f"_{name}", None)
        if stamped is not None:
            return stamped
        hook = getattr(view, f"get_{action}_{name}", None)
        if hook is not None:
            return hook
    return get_class_attr(view, name)


class MountedView:
    """A view class read through ``overrides``: each name from them first, then from the class."""

    __name__: str

    def __init__(self, base: Any, overrides: Mapping[str, Any], *, name: str) -> None:
        self._mounted_base = base
        self._mounted_overrides = dict(overrides)
        self.__name__ = name

    def __getattr__(self, name: str) -> Any:
        overrides: dict[str, Any] = self._mounted_overrides
        return overrides[name] if name in overrides else getattr(self._mounted_base, name)

    def __dir__(self) -> list[str]:
        return dir(self._mounted_base)


def mounted_view(view_cls: type, initkwargs: Mapping[str, Any]) -> MountedView:
    """``view_cls`` as every instance ``as_view(**initkwargs)`` builds answers it."""
    return MountedView(view_cls, initkwargs, name=view_cls.__name__)


def resolve_callable_kwargs(
    fn: Callable[..., Any],
    pool: dict[str, Any],
) -> dict[str, Any]:
    """Pick the subset of ``pool`` matching ``fn``'s declared parameters."""
    signature: inspect.Signature = inspect.signature(fn)
    params: dict[str, inspect.Parameter] = dict(signature.parameters)

    accepts_var_keyword: bool = any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
    )
    if accepts_var_keyword:
        return dict(pool)

    declared_names: set[str] = {
        name
        for name, param in params.items()
        if param.kind
        in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }
    return {name: pool[name] for name in declared_names if name in pool}


def resolve_progress_hook(view: Any, request: Request, *, action: str | None) -> Any:
    """First progress reporter the view offers: per-action hook, then catch-all."""
    pool: dict[str, Any] = {
        "view": view,
        "request": request,
        "call_context": view_call_context(view, request),
    }
    for name in (f"get_{action}_progress_reporter" if action else None, "get_progress_reporter"):
        hook = getattr(view, name, None) if name else None
        if hook is not None:
            reporter = hook(**bind_by_name_only(hook, pool))
            if reporter is not None:
                return reporter
    return None


def resolve_view_hooks(
    view: Any,
    request: Request,
    *,
    instance: Any = None,
) -> ViewHooks:
    """Resolve the calling view's hook chains into a [`ViewHooks`][django_spec_rest.types.view_hooks.ViewHooks] carrier."""  # noqa: E501
    action: str | None = getattr(view, "action", None)
    extra_kwargs = resolve_extra_kwargs(
        view,
        request,
        action_hook=f"get_{action}_service_kwargs" if action else None,
        catch_all_hook="get_service_kwargs",
    )
    progress = resolve_progress_hook(view, request, action=action)
    return ViewHooks(
        extra_kwargs=extra_kwargs,
        progress=progress,
        input_data=resolve_input_extras(
            view,
            request,
            action_hook=f"get_{action}_input_data" if action else None,
            catch_all_hook="get_input_data",
            extras={"instance": instance},
        ),
        input_serializer_context=layer_serializer_context(
            {},
            view,
            request,
            direction_hook="get_input_serializer_context",
            action_hook=f"get_{action}_input_serializer_context" if action else None,
        ),
        output_serializer_context=lambda result: layer_serializer_context(
            {},
            view,
            request,
            direction_hook="get_output_serializer_context",
            action_hook=f"get_{action}_output_serializer_context" if action else None,
            extras={"result": result},
        ),
    )


class _JsonNullResponse(Response):
    """The ``200`` an ``allow_none`` RETRIEVE serves for a miss: a JSON ``null`` body."""

    def __init__(self) -> None:
        super().__init__(None)

    @property
    def rendered_content(self) -> Any:
        rendered: Any = super().rendered_content
        renderer: Any = self.accepted_renderer
        # Each operand held by test_a_json_renderer_that_wraps_none_keeps_its_wrapper and kin.
        if rendered or not isinstance(renderer, JSONRenderer):
            return rendered
        charset: str | None = renderer.charset
        self["Content-Type"] = (
            renderer.media_type if charset is None else f"{renderer.media_type}; charset={charset}"
        )
        return b"null"


def presented_response(
    view: Any, spec: Any, presented: Any, *, status: int = 200
) -> HttpResponseBase:
    """DRF's ``Response`` of ``presented``, or the file where ``spec`` presents one."""
    if file_output(spec) is None:
        return Response(presented, status=status)
    attachment = get_class_attr(view, "as_attachment") is not False
    content = presented.content
    response: HttpResponseBase
    if isinstance(content, bytes) or hasattr(content, "read"):
        response = FileResponse(
            io.BytesIO(content) if isinstance(content, bytes) else content,
            status=status,
            as_attachment=attachment,
            filename=presented.filename,
            content_type=presented.content_type,
        )
    else:
        response = StreamingHttpResponse(
            content, status=status, content_type=presented.content_type
        )
        response["Content-Disposition"] = (
            content_disposition_header(attachment, presented.filename) or "inline"
        )
    if presented.size is not None:
        response["Content-Length"] = str(presented.size)
    return response


class _NegotiatesAFile:
    """Serves a spec's file under an ``Accept`` naming its type, which no renderer offers.

    ``as_attachment``: whether the file answers as a download, or ``inline`` for a browser."""

    as_attachment: bool = True

    def perform_content_negotiation(self, request: Request, force: bool = False) -> Any:
        negotiate = super().perform_content_negotiation  # ty: ignore[unresolved-attribute]
        try:
            return negotiate(request, force)
        except NotAcceptable:
            if not _accepts_a_file_of(request, _served_spec(self)):
                raise
            return negotiate(request, force=True)


def _served_spec(view: Any) -> Any:
    """The spec ``view`` serves this request: its ``spec``, ``action_specs`` or a stamp."""
    from django_spec_rest.viewsets.utils import resolve_action_spec_entry

    spec = getattr(view, "spec", None)
    action = getattr(view, "action", None)
    if spec is not None or not isinstance(action, str):
        return spec
    entry = resolve_action_spec_entry(getattr(view, "action_specs", {}), action)
    handler = getattr(view, action, None)
    stamped = getattr(handler, "_service_spec", None) or getattr(handler, "_selector_spec", None)
    return entry if entry is not None else stamped


def _accepts_a_file_of(request: Request, spec: Any) -> bool:
    """Whether ``request``'s ``Accept`` admits a file ``spec`` (any variant) presents."""
    if spec is None:
        return False
    variants = spec.specs.values() if isinstance(spec, DiscriminatedAction) else [spec]
    files = [file for file in map(file_output, variants) if file is not None]
    accepted = [part.strip() for part in request.META.get("HTTP_ACCEPT", "*/*").split(",")]
    return any(media_type_matches(a, f.content_type) for a in accepted for f in files)
