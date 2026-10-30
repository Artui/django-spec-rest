"""Cross-cutting view helpers used by both mutation and query views."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from django_service_specs.pool.resolve_callable_kwargs import (
    resolve_callable_kwargs as bind_by_name_only,
)
from django_service_specs.types.unset import UNSET
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response

from django_spec_rest.dispatch.utils import fill_call_context
from django_spec_rest.types.view_hooks import ViewHooks


def resolve_extra_kwargs(
    view: Any,
    request: Request,
    *,
    action_hook: str | None,
    catch_all_hook: str,
) -> dict[str, Any]:
    """Collect the extras that should be merged into a service/selector pool.

    Two layers, merged with ``dict.update`` in increasing specificity so the
    per-action hook has the final say on overlapping keys. Each is invoked
    through the framework's provider convention (``_invoke_provider``),
    receiving only the subset of ``{view, request, call_context}`` it declares,
    or ``{view, request}`` via ``**kwargs``: the call's context is offered by
    name only. The spec's own ``kwargs`` provider is the kernel's layer and runs
    there, so resolving it here too would invoke it twice.

    Args:
        action_hook: Per-action view method, e.g. ``get_create_service_kwargs``
            / ``get_list_selector_kwargs``. ``None`` (standalone single-purpose
            views) or an absent method skips the layer.
        catch_all_hook: View-wide fallback, e.g. ``get_service_kwargs`` /
            ``get_selector_kwargs``. An absent method skips the layer.
    """
    extras: dict[str, Any] = {}
    # The request's one dict, for every layer. Its hand-off to the two view
    # hooks is held by test_every_viewset_hook_naming_the_call_context_is_handed_the_view_s_dict.
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
    """Collect the extras to merge into the serializer input dict.

    ``resolve_extra_kwargs``'s layering — ``catch_all_hook`` view method,
    then ``action_hook`` — applied to the ``input_serializer``-bound data rather than the
    service-call pool.

    Args:
        extras: The resolved data available before validation — currently the
            mutation target ``instance``, ``None`` on create — offered to each
            provider by keyword only when it declares the name.
    """
    payload: Mapping[str, Any] = extras if extras is not None else {}
    collected: dict[str, Any] = {}
    # As in ``resolve_extra_kwargs``: the hand-off is held by
    # test_every_viewset_hook_naming_the_call_context_is_handed_the_view_s_dict.
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


def view_call_context(view: Any, request: Request) -> dict[str, Any]:
    """The call's context of the request ``view`` is serving: one dict per request.

    Built on first use with the edge's four standard entries (``request``,
    ``view``, ``format``, the route's suffix or ``None``, and the view's
    ``action`` or ``None``) and kept on the view, which DRF builds afresh for every request, so a second request
    is a second dict (test_each_request_is_a_dict_of_its_own). Kept rather than
    rebuilt: a dict per caller fails the identity assertions of
    test_every_callable_of_a_kernel_service_is_handed_the_view_s_dict. Two
    dispatches in one request, the retrieve spec finding an update's row and
    then the update spec, are one call and share it.

    A view hands this object to the kernel's ``dispatch`` as its
    ``call_context=``, so the spec's own callables are offered it as
    the edge offers them, and it offers it itself to each callable it invokes:

    - the hooks ``get_service_kwargs``, ``get_input_data``,
      ``get_input_serializer_context`` and ``get_output_serializer_context``,
      and the per-action form of each (``get_<action>_service_kwargs`` and so
      on);
    - ``get_progress_reporter`` and ``get_<action>_progress_reporter``.

    Each is offered it **by name only**, as the kernel binds it: a callable
    declaring a ``call_context`` parameter is handed this dict, and one taking
    ``**kwargs`` alone never is, so its keys, and a serializer context built
    from them, carry no ``call_context``
    (test_a_view_hook_taking_kwargs_alone_is_never_handed_the_call_context).
    ``success_status`` and ``response_finalizer`` are not offered it, and one
    declaring it is refused when the view is built, by
    ``validate_mutation_view_spec``: a standalone mutation view's over its
    ``spec``, and a viewset's over each ``action_specs`` entry, which its
    ``as_view()`` asks as the standalone view asks of its spec
    (test_a_status_or_finalizer_naming_the_call_context_is_refused_when_the_view_is_built).
    """
    context: dict[str, Any] | None = getattr(view, "_call_context", None)
    if context is None:
        # ``format`` is the route's suffix, which DRF's view keeps as
        # ``format_kwarg`` (none on a route with no suffix, or a view that never ran
        # DRF's ``initial``): the answer ``get_serializer_context`` gives for it, so a
        # hyperlink a serializer builds from this dict carries the suffix
        # (test_a_suffix_route_s_format_is_in_the_one_dict_the_validator_reads).
        context = fill_call_context(
            {"format": getattr(view, "format_kwarg", None)}, request=request, view=view
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
    """Call ``fn`` with the subset of ``{view, request, call_context, **extras}`` it declares.

    The single provider-invocation convention: the spec-level ``kwargs`` /
    ``input_data`` / ``*_serializer_context`` callables and the view's ``get_*``
    hooks all come through here, bound by the kernel's rule exactly as
    services and selectors are. Bound view-method hooks simply don't
    declare ``view`` (it is their ``self``), so it is filtered out for them.

    ``call_context`` is the request's dict (``view_call_context``), the one
    object the edge hands its own stages; every caller in the package passes
    it, so a provider naming it is answered on every view
    (test_every_viewset_hook_naming_the_call_context_is_handed_the_view_s_dict). Left out, the pool has
    no such name. It is offered by name only, through the kernel's binder
    rather than ``resolve_callable_kwargs``, so a provider taking ``**kwargs``
    sees the keys it always did
    (test_a_view_hook_taking_kwargs_alone_is_never_handed_the_call_context
    fails with the local binder) and one naming it is handed it
    (test_every_viewset_hook_naming_the_call_context_is_handed_the_view_s_dict).

    A returned key whose value is ``UNSET`` is
    **dropped** — the provider is declining to set it rather than setting it to
    ``UNSET``. This mirrors the off-HTTP
    ``resolve_provider`` so the
    sentinel means the same thing on every transport.
    """
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
    """Layer the directional and action context hooks onto ``base``.

    Merged with ``dict.update`` in increasing specificity: ``base`` (DRF's
    ``view.get_serializer_context()``, handed in so an override of that method
    can extend ``super()``'s result without recursing) -> ``view.<direction_hook>()``
    -> ``view.<action_hook>()``. An absent view method skips its layer, so plain
    DRF viewsets work unchanged.

    Args:
        direction_hook: ``get_input_serializer_context`` /
            ``get_output_serializer_context``.
        action_hook: Per-action override, e.g.
            ``get_create_input_serializer_context``. ``None`` on standalone
            single-purpose views.
        extras: The resolved data about to be serialized (a mutation's
            ``result``), offered to each layer by keyword only when declared.
    """
    payload: Mapping[str, Any] = extras if extras is not None else {}
    # The request's one dict, the object the edge handed its own stages. Each
    # layer's hand-off, the directional hook's and the action hook's, is held
    # by test_every_viewset_hook_naming_the_call_context_is_handed_the_view_s_dict.
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
    """Return the named class attribute without instance binding.

    A function stored as a plain class attribute (``service = my_fn``) would
    otherwise be wrapped in a bound method when read via ``self``.
    """
    return getattr(type(view), name, None)


def resolve_callable_kwargs(
    fn: Callable[..., Any],
    pool: dict[str, Any],
) -> dict[str, Any]:
    """Pick the subset of ``pool`` matching ``fn``'s declared parameters.

    If ``fn`` declares ``**kwargs``, the entire pool is passed.
    Otherwise only parameters present in the signature are forwarded.
    """
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
    """First progress reporter the view offers: per-action hook, then catch-all.

    Most-specific wins and there is **no merging** — a reporter is a single sink,
    not a set of keys, so layering two of them would mean silently fanning out;
    a view that wants that composes them itself with
    ``combine_progress``. ``None`` when the view
    offers neither, which leaves the seed as
    [`null_progress`][django_service_specs.pool.null_progress.null_progress].

    A hook naming ``call_context`` is handed the request's dict
    (``view_call_context``), and one taking ``**kwargs`` alone is not.
    """
    # The request's dict, offered by name only through the kernel's binder.
    # test_every_viewset_hook_naming_the_call_context_is_handed_the_view_s_dict
    # fails without the entry, and the ``get_progress_reporter`` case of
    # test_a_view_hook_taking_kwargs_alone_is_never_handed_the_call_context with the
    # local binder.
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


# Lives here rather than beside the mutation flow because the selector path
# needs it too, and ``views.mutation.utils`` imports ``selectors.utils`` —
# putting it there would make the dependency circular.
def resolve_view_hooks(
    view: Any,
    request: Request,
    *,
    instance: Any = None,
) -> ViewHooks:
    """Resolve the calling view's hook chains into a
    [`ViewHooks`][django_spec_rest.types.view_hooks.ViewHooks] carrier.

    **View layers only.** The chains run ``view.get_<x>`` → ``view.get_<action>_<x>`` →
    ``spec.<x>``, and the kernel owns that last layer; resolving the spec provider here
    too would invoke it **twice**, which is not safe for a provider that queries the
    database. See [`ViewHooks`][django_spec_rest.types.view_hooks.ViewHooks].

    Args:
        instance: The resolved mutation target (``None`` on create and on every
            bulk path), offered to the ``input_data`` providers that declare it.
    """
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
    """The ``200`` an ``allow_none`` RETRIEVE serves for a miss: a JSON ``null`` body.

    ``Response(None)`` alone is not that. DRF's ``JSONRenderer`` renders ``None``
    as an empty body, and ``Response`` then deletes the ``Content-Type`` it had
    set, so a client received ``200`` with no body and no media type, and
    ``response.json()`` raised on a contract that promises ``null``.

    The fix is a response rather than a renderer because a response acts *after*
    negotiation, and only on the branch that builds it. The view's
    ``renderer_classes`` -- and a project's ``DEFAULT_RENDERER_CLASSES``, which
    may name a JSON renderer of its own -- stay exactly as configured, and a found
    row never comes through here.

    The negotiated renderer still renders the miss, so whatever it makes of
    ``None`` is served: an envelope renderer's ``{"data": null}``, the browsable
    API's page, a plain-text renderer's text. Only an *empty* body from a
    ``JSONRenderer``, subclasses included, becomes the literal ``null``, under
    the ``Content-Type`` DRF gives that renderer's other bodies: its media type,
    with ``; charset=`` when it declares one. Any other renderer's empty body is
    served as DRF serves it.
    """

    def __init__(self) -> None:
        super().__init__(None)

    @property
    def rendered_content(self) -> Any:
        rendered: Any = super().rendered_content
        renderer: Any = self.accepted_renderer
        # One boolean, so each operand is held by a named test in
        # tests/views/test_selector_retrieve_view.py: ``rendered`` by
        # test_a_json_renderer_that_wraps_none_keeps_its_wrapper, and the
        # renderer type by
        # test_a_non_json_renderer_that_renders_none_as_nothing_still_does.
        if rendered or not isinstance(renderer, JSONRenderer):
            return rendered
        # DRF deleted the header it had set, because the body was empty. Set it
        # back the way ``Response.rendered_content`` built it; this response
        # never takes a ``content_type``, so the renderer's own is the one.
        # The charset half is held by
        # test_a_charset_renderer_serves_a_miss_under_the_header_of_a_found_row.
        charset: str | None = renderer.charset
        self["Content-Type"] = (
            renderer.media_type if charset is None else f"{renderer.media_type}; charset={charset}"
        )
        return b"null"
