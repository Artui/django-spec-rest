from __future__ import annotations

import inspect
import warnings
from collections.abc import Iterator
from typing import Any

from django_spec_rest.views.utils import MountedView
from django_spec_rest.viewsets.get_queryset_scope_warning import GetQuerysetScopeWarning

_THE_ID = "django_spec_rest.W001"
_THE_PAGE = "https://artui.github.io/django-spec-rest/moving-from-drfs/#views-and-viewsets"
_SILENCED_BY = "spec_rows_scoped_by_selector"

# ``SelectorListMixin``, ``SelectorListView`` and DRF's ``GenericAPIView`` define
# ``get_queryset`` themselves, and none of them is a project's override.
_OWN_PACKAGES = frozenset({"django_spec_rest", "rest_framework"})


def _overriding_classes(view_cls: type, name: str = "get_queryset") -> list[type]:
    """Every class above ``view_cls`` defining ``name``, other than this package's or DRF's."""
    return [
        klass
        for klass in view_cls.__mro__
        if name in vars(klass) and klass.__module__.partition(".")[0] not in _OWN_PACKAGES
    ]


def _specs_served(mounted: MountedView) -> Iterator[object]:
    """Each spec ``mounted`` serves: its ``action_specs`` entries, then the decorators' stamps."""
    yield from mounted.action_specs.values()
    for _, member in inspect.getmembers(mounted):
        stamped = getattr(member, "_service_spec", None) or getattr(member, "_selector_spec", None)
        if stamped is not None:
            yield stamped


def _vouched_for(view_cls: type, overriding: list[type]) -> bool:
    """Whether the nearest ``spec_rows_scoped_by_selector`` covers every override."""
    for klass in view_cls.__mro__:
        if _SILENCED_BY in vars(klass):
            return bool(vars(klass)[_SILENCED_BY]) and all(
                issubclass(klass, override) for override in overriding
            )
    return False


def warn_unscoped_get_queryset(mounted: MountedView) -> None:
    """Warn where the class ``mounted`` reads overrides ``get_queryset()`` beside any spec."""
    view_cls: Any = mounted._mounted_base
    overriding = _overriding_classes(view_cls)
    if (
        not overriding
        or not any(True for _ in _specs_served(mounted))
        or _vouched_for(view_cls, overriding)
    ):
        return
    names = ", ".join(klass.__qualname__ for klass in overriding)
    warnings.warn(
        f"{_THE_ID}: {view_cls.__module__}.{view_cls.__qualname__} overrides get_queryset() "
        f"(on {names}) and serves a spec, whose rows come from the spec's own selector, "
        "never from get_queryset(). Scoping left there narrows nothing, so a PATCH, DELETE "
        "or GET reaches a row it would have hidden, with no error. Move it into each "
        f"selector's own queryset ({_THE_PAGE}), then set {_SILENCED_BY} = True on the class.",
        GetQuerysetScopeWarning,
        stacklevel=3,
    )
