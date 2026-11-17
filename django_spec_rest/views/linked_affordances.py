from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured
from django.urls import NoReverseMatch, get_script_prefix, resolve
from django_service_specs.affordances.utils import AFFORDANCES_KEY
from django_service_specs.links.link_bindings import link_bindings
from django_service_specs.links.row_links import row_links
from django_service_specs.registry.spec_registry import SpecRegistry
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.service_spec import ServiceSpec
from rest_framework.reverse import reverse

from django_spec_rest.types.discriminated_action import DiscriminatedAction
from django_spec_rest.views.utils import resolve_action_spec_entry

# The methods a link names, in ``View.http_method_names`` order: PUT before PATCH.
LINK_METHODS = ("post", "put", "patch", "delete")


def linked_affordances(view: Any, spec: Any, presented: Any, *, many: bool) -> Any:
    """``presented`` with ``href`` and ``method`` in each entry ``view.link_routes`` names."""
    routes = getattr(view, "link_routes", None)
    if routes is None:
        return presented
    link_bindings(spec)
    shaped = kernel_spec(spec).output() is not None
    methods: dict[str, str | None] = {}
    if many:
        return [_linked(view, spec, item, routes, shaped, methods) for item in presented]
    return _linked(view, spec, presented, routes, shaped, methods)


def _linked(
    view: Any, spec: Any, item: Any, routes: SpecRegistry, shaped: bool, methods: dict[str, Any]
) -> Any:
    try:
        links = row_links(spec, item, registry=routes)
    except ImproperlyConfigured:
        # Fields an output declares are checked, so a row lacking one was shaped; else a typo.
        if not shaped:
            raise
        return item
    if not links:
        return item
    answers = dict(item[AFFORDANCES_KEY])
    for name, link in links.items():
        route = link.get("name")
        found = None if route is None else _call(view, route, link, routes, methods)
        if found is not None:
            answers[name] = {**answers[name], "href": found[0], "method": found[1]}
    return {**item, AFFORDANCES_KEY: answers}


def _call(
    view: Any, route: str, link: Mapping[str, Any], routes: SpecRegistry, methods: dict[str, Any]
) -> tuple[str, str] | None:
    """The href, reversed with the required reads alone, and the method, found once a response."""
    kwargs = {read: link["arguments"][read] for read in link["required"]}
    try:
        href = reverse(route, kwargs=kwargs, request=view.request)
    except NoReverseMatch:
        return None
    if route not in methods:
        methods[route] = _method(href, route, routes)
    method = methods[route]
    return None if method is None else (href, method)


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
    view_class = getattr(func, "cls", None)
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
    return isinstance(served, ServiceSpec) and routes.name_of(served) == route
