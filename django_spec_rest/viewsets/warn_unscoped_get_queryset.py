"""Report a viewset whose ``get_queryset()`` override no longer scopes what its specs serve.

A warning at ``as_view()`` rather than a Django system check, because this package has no
``AppConfig`` for one to live on and a project is told to list none: a check registered by
an ``AppConfig`` is silent for exactly the project that forgets the entry. Registering one
when this package is imported does not serve either. A project first imports a viewset from
its URLconf, which ``manage.py check`` reaches during its URL check, after Django has taken
its list of checks for that run, so the check would run on no first ``check`` of a process.
``as_view()`` is the one point every mounted viewset passes through, and a warning there
is printed by ``check``, ``runserver`` and a WSGI import alike, and is one a test suite can
assert on or turn into an error.
"""

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


def _overriding_classes(view_cls: type) -> list[type]:
    """Every class above ``view_cls`` defining ``get_queryset``, other than this package's or DRF's.

    Read off the MRO rather than through ``view_cls.get_queryset``: a project's mixin listed
    after ``SelectorListMixin`` resolves to the package's method, whose ``super()`` runs it
    (test_from_a_mixin_below_the_package_s_own_bases).
    """
    return [
        klass
        for klass in view_cls.__mro__
        if "get_queryset" in vars(klass) and klass.__module__.partition(".")[0] not in _OWN_PACKAGES
    ]


def _specs_served(mounted: MountedView) -> Iterator[object]:
    """Each spec ``mounted`` serves: its ``action_specs`` entries, then the decorators' stamps.

    An ``as_view(action_specs=...)`` reads through ``mounted``, as the instance will.
    """
    yield from mounted.action_specs.values()
    for _, member in inspect.getmembers(mounted):
        stamped = getattr(member, "_service_spec", None) or getattr(member, "_selector_spec", None)
        if stamped is not None:
            yield stamped


def _vouched_for(view_cls: type, overriding: list[type]) -> bool:
    """Whether the nearest ``spec_rows_scoped_by_selector`` covers every override.

    Inherited, so a project's base carrying an eager-loading override says so once; but a
    class vouches only for what it could have read, itself and its own bases. An override
    added beneath it, by a subclass or a mixin listed before it, is one nobody has looked
    at, and tenant scoping is what that would silently drop
    (test_a_base_never_vouches_for_a_subclass_s_own_override,
    test_a_base_never_vouches_for_an_override_added_beneath_it).
    """
    for klass in view_cls.__mro__:
        if _SILENCED_BY in vars(klass):
            return bool(vars(klass)[_SILENCED_BY]) and all(
                issubclass(klass, override) for override in overriding
            )
    return False


def warn_unscoped_get_queryset(mounted: MountedView) -> None:
    """Warn where the class ``mounted`` reads overrides ``get_queryset()`` beside any spec.

    Under this package a spec's rows are its selector's, whatever it is (a write's target,
    a list's set, a retrieve's row), so tenant scoping left in ``get_queryset()`` narrows
    nothing, and a ``PATCH``, ``DELETE`` or ``GET`` reaches another tenant's row with no
    error. Only an action with no spec takes its rows from ``get_queryset()``, and is not
    reported.

    Asked once per ``as_view()``, never per request. A router mounts a viewset once per
    route, all from one line, and the text is the same for each, so Python's default filter
    shows it once (test_a_router_mounting_a_viewset_twice_shows_it_once). ``stacklevel`` names
    the line calling ``as_view()``, past this function and ``as_view()`` itself
    (test_it_names_the_line_mounting_the_viewset).
    """
    view_cls: Any = mounted._mounted_base
    overriding = _overriding_classes(view_cls)
    # One arc to coverage, so each conjunct is named: the override by
    # test_with_no_override_over_the_package_s_own_get_queryset, the spec by
    # test_for_a_spec_less_action, the silencing by test_the_class_declaring_it_is_silent.
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
