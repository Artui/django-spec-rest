from __future__ import annotations

from collections.abc import Mapping
from itertools import combinations
from typing import Any
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured
from django.urls import NoReverseMatch, get_script_prefix, resolve
from django_service_specs.affordances.utils import AFFORDANCES_KEY
from django_service_specs.links.link_bindings import link_bindings
from django_service_specs.links.row_links import row_links
from django_service_specs.registry.spec_registry import SpecRegistry
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from rest_framework.reverse import reverse

from django_spec_rest.types.discriminated_action import DiscriminatedAction
from django_spec_rest.views.utils import resolve_action_spec_entry

# The methods a link names, in ``View.http_method_names`` order: PUT before PATCH.
LINK_METHODS = ("get", "post", "put", "patch", "delete")


def linked_affordances(view: Any, spec: Any, presented: Any, *, many: bool) -> Any:
    """``presented`` with ``href`` and ``method`` in each entry ``view.link_routes`` names."""
    routes = getattr(view, "link_routes", None)
    if routes is None:
        return presented
    link_bindings(spec)
    resolved: dict[tuple[str, frozenset[str]], Any] = {}
    if many:
        return [_linked(view, spec, item, routes, resolved) for item in presented]
    return _linked(view, spec, presented, routes, resolved)


def _linked(view: Any, spec: Any, item: Any, routes: SpecRegistry, resolved: dict[Any, Any]) -> Any:
    try:
        links = row_links(spec, item, registry=routes)
    except ImproperlyConfigured:
        # Bindings were checked above, so this is a row a shape left a bound field out of.
        return item
    if not links:
        return item
    answers = dict(item[AFFORDANCES_KEY])
    for name, link in links.items():
        route = link.get("name")
        found = None if route is None else _call(view, route, link, routes, resolved)
        if found is not None:
            answers[name] = {**answers[name], "href": found[0], "method": found[1]}
    return {**item, AFFORDANCES_KEY: answers}


def _call(
    view: Any,
    route: str,
    link: Mapping[str, Any],
    routes: SpecRegistry,
    resolved: dict[Any, Any],
) -> tuple[str, str] | None:
    """The href and method of one link, or ``None``; a route that reversed is kept per response."""
    arguments: dict[str, Any] = link["arguments"]
    key = (route, frozenset(arguments))
    known = resolved.get(key) or _route(view, route, arguments, routes)
    if known is None:
        return None
    resolved[key] = known
    captures, method = known
    if method is None:
        return None
    try:
        return reverse(
            route, kwargs={read: arguments[read] for read in captures}, request=view.request
        ), method
    except NoReverseMatch:
        return None


def _route(
    view: Any, route: str, arguments: Mapping[str, Any], routes: SpecRegistry
) -> tuple[tuple[str, ...], str | None] | None:
    """The arguments ``route`` captures, the largest set that reverses, and its method."""
    for size in range(len(arguments), -1, -1):
        for captures in combinations(arguments, size):
            try:
                href = reverse(
                    route, kwargs={read: arguments[read] for read in captures}, request=view.request
                )
            except NoReverseMatch:
                continue
            return captures, _method(href, route, routes)
    return None


def _method(href: str, route: str, routes: SpecRegistry) -> str | None:
    """The first method the view at ``href`` (less the script prefix) serves ``route``'s spec."""
    path = "/" + urlsplit(href).path[len(get_script_prefix()) :]
    served = _served(resolve(path).func)
    for method in LINK_METHODS:
        if method in served and _serves(served[method], route, routes):
            return method.upper()
    return None


def _served(func: Any) -> dict[str, Any]:
    """What each method of a mounted view serves: its ``spec``, ``action_specs`` or a stamp."""
    view_class = getattr(func, "cls", None) or getattr(func, "view_class", None)
    initkwargs: Mapping[str, Any] = getattr(func, "initkwargs", {})
    actions: Mapping[str, str] | None = getattr(func, "actions", None)

    def attr(name: str) -> Any:
        return initkwargs[name] if name in initkwargs else getattr(view_class, name, None)

    if actions is None:
        return {method: attr("spec") for method in LINK_METHODS if hasattr(view_class, method)}
    action_specs = attr("action_specs") or {}
    served: dict[str, Any] = {}
    for method, action in actions.items():
        entry = resolve_action_spec_entry(action_specs, action)
        handler = getattr(view_class, action, None)
        served[method] = entry if entry is not None else getattr(handler, "_service_spec", None)
    return served


def _serves(served: Any, route: str, routes: SpecRegistry) -> bool:
    if isinstance(served, DiscriminatedAction):
        return any(_serves(variant, route, routes) for variant in served.specs.values())
    if isinstance(served, ServiceSpec | SelectorSpec):
        return routes.name_of(served) == route
    return False
