"""Where the package reaches into DRF and into its own HTTP views, held as ratchets.

The kernel's ``dispatch`` is the one transport-neutral execution path, and this
package is its HTTP edge: the views read a request into the kernel's arguments and
answer its result as DRF. Every module outside the HTTP transport that imports
``rest_framework`` or ``django_spec_rest.views`` is a place the edge's helpers
depend on the transport they sit beneath, so each is listed.

These are not bans. Most entries below are legitimate today — the offline request
types are DRF's ``Request``, and the call-context resolver lives in
``views/utils.py`` beside the view helpers that share it. What the tests forbid is
**growth without a decision**: an import that is not listed fails,
and so does a listed import that no longer exists, so the lists can only shrink
and every shrink is recorded here rather than lost.

Each allowlist is keyed by module path relative to the package, with the modules
it imports. A ``from pkg import name`` counts as importing ``pkg.name`` when that
is a module, so ``from rest_framework import serializers`` is recorded as
``rest_framework.serializers`` rather than as the whole of DRF.

The walk reads every ``import`` in the file — top level, function-local and under
``TYPE_CHECKING`` alike — because a deferred import is still a dependency; it is
only a later one.
"""

from __future__ import annotations

import ast
import importlib.util
from collections.abc import Iterator
from functools import cache
from pathlib import Path

import django_spec_rest

PACKAGE_ROOT = Path(django_spec_rest.__file__).parent

# The HTTP transport. Importing DRF, or each other, is what these are for.
# ``openapi`` is the drf-spectacular integration, which exists only over HTTP.
TRANSPORT_PACKAGES = frozenset({"views", "viewsets", "openapi"})

# The adapter over django-service-specs: it gives a kernel spec its DRF seats (a
# serializer as Validator and Presenter, DRF's permission classes as a check) and
# translates the kernel's answers back into DRF's. Importing DRF is what it is
# for (the serializer is its Validator and its Presenter, DRF's permission classes
# are its guard), so it is walled by a ratchet of its own below rather than held to
# the neutral core's. It must never reach the HTTP views.
EDGE_PACKAGES = frozenset({"service_specs"})

# The package root re-exports the public surface, the HTTP views included, so its
# imports say nothing about which layer depends on which.
EXEMPT_MODULES = frozenset({"__init__.py"})

VIEWS_PREFIXES = ("django_spec_rest.views", "django_spec_rest.viewsets")
DRF_PREFIXES = ("rest_framework",)

# Modules outside the transport that import the HTTP views, and what they import.
ALLOWED_VIEWS_IMPORTS: dict[str, frozenset[str]] = {
    # The kernel route's refusal map answers every ``ServiceError`` with
    # ``map_service_error``, so the ``AdditionalInputRequired`` schema
    # ``restore_raised_schema`` recognises by class is restored.
    "dispatch/kernel_refusals.py": frozenset({"django_spec_rest.views.mutation.map_service_error"}),
    "selectors/utils.py": frozenset({"django_spec_rest.views.utils"}),
}

# Modules outside the transport that import DRF, and which of its modules.
ALLOWED_DRF_IMPORTS: dict[str, frozenset[str]] = {
    # The DRF edge over the kernel's own ``dispatch``. ``request`` is for
    # annotations alone: the ``Request`` whose body and query string it reads is
    # handed in.
    "dispatch/kernel_edge.py": frozenset({"rest_framework.request"}),
    # The kernel route's refusal map answers each kernel refusal as a DRF
    # exception (``exceptions``), the bare ``DispatchError``'s under a ``400`` it
    # declares (``status``).
    "dispatch/kernel_refusals.py": frozenset(
        {
            "rest_framework.exceptions",
            "rest_framework.status",
        }
    ),
    "selectors/utils.py": frozenset(
        {
            "rest_framework.exceptions",
            "rest_framework.request",
            # ``URL_FORMAT_OVERRIDE``: ``?format`` is one of DRF's own query
            # keys, which ``kernel_query`` keeps off a kernel spec's arguments.
            "rest_framework.settings",
            # ``QueryParameterVersioning``: of DRF's versioning classes only
            # this one reads ``?version``, so only it names a query key.
            "rest_framework.versioning",
        }
    ),
    "types/http_extras.py": frozenset({"rest_framework.request"}),
    "types/offline_context.py": frozenset({"rest_framework.request"}),
    "types/offline_service_view.py": frozenset({"rest_framework.request"}),
    "types/service_view.py": frozenset({"rest_framework.request"}),
}


@cache
def _is_module(dotted: str) -> bool:
    try:
        return importlib.util.find_spec(dotted) is not None
    except (ImportError, ValueError):
        # ``find_spec`` imports the parent to look inside it; a parent that is
        # itself not a package raises rather than answering ``None``.
        return False


def _imported_modules(tree: ast.AST) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            for alias in node.names:
                candidate = f"{node.module}.{alias.name}"
                yield candidate if _is_module(candidate) else node.module


def _is_outside_transport(relative: Path) -> bool:
    if relative.as_posix() in EXEMPT_MODULES:
        return False
    return relative.parts[0] not in TRANSPORT_PACKAGES | EDGE_PACKAGES


def _is_edge(relative: Path) -> bool:
    return relative.parts[0] in EDGE_PACKAGES


def _imports_matching(
    prefixes: tuple[str, ...], *, edge: bool = False
) -> dict[str, frozenset[str]]:
    found: dict[str, frozenset[str]] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        relative = path.relative_to(PACKAGE_ROOT)
        if not (_is_edge(relative) if edge else _is_outside_transport(relative)):
            continue
        targets = frozenset(
            module
            for module in _imported_modules(ast.parse(path.read_text(encoding="utf-8")))
            if any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)
        )
        if targets:
            found[relative.as_posix()] = targets
    return found


def _difference(
    left: dict[str, frozenset[str]], right: dict[str, frozenset[str]]
) -> dict[str, list[str]]:
    return {
        module: sorted(targets - right.get(module, frozenset()))
        for module, targets in left.items()
        if targets - right.get(module, frozenset())
    }


def test_no_new_import_of_the_http_views_outside_the_transport() -> None:
    added = _difference(_imports_matching(VIEWS_PREFIXES), ALLOWED_VIEWS_IMPORTS)
    assert not added, (
        f"New imports of the HTTP views from outside the transport: {added}. Move what "
        "the module needs out of views/ into the layer that owns it, or, if the "
        "module is itself HTTP-only, file it under a transport package. Adding it to "
        "ALLOWED_VIEWS_IMPORTS is a decision to widen the coupling; say why beside it."
    )


def test_every_allowed_views_import_still_exists() -> None:
    gone = _difference(ALLOWED_VIEWS_IMPORTS, _imports_matching(VIEWS_PREFIXES))
    assert not gone, (
        f"These allowed imports of the HTTP views no longer exist: {gone}. Remove them "
        "from ALLOWED_VIEWS_IMPORTS, so the list keeps recording what is left."
    )


def test_no_new_import_of_drf_outside_the_transport() -> None:
    added = _difference(_imports_matching(DRF_PREFIXES), ALLOWED_DRF_IMPORTS)
    assert not added, (
        f"New imports of DRF from outside the transport: {added}. The dispatch core "
        "runs with no DRF object constructed; a new dependency on DRF there is a "
        "step away from that. Adding it to ALLOWED_DRF_IMPORTS is a decision to "
        "widen the coupling; say why beside it."
    )


def test_every_allowed_drf_import_still_exists() -> None:
    gone = _difference(ALLOWED_DRF_IMPORTS, _imports_matching(DRF_PREFIXES))
    assert not gone, (
        f"These allowed imports of DRF no longer exist: {gone}. Remove them from "
        "ALLOWED_DRF_IMPORTS, so the list keeps recording what is left."
    )


# Modules of the adapter and the DRF modules each imports. Listed so that growth is a
# decision: the adapter is the one place the neutral core's DRF dependencies are
# supposed to concentrate.
ALLOWED_EDGE_DRF_IMPORTS: dict[str, frozenset[str]] = {
    "service_specs/build_offline_context.py": frozenset({"rest_framework.request"}),
    # A DRF permission class is the guard the kernel's PermissionCheck wraps.
    "service_specs/drf_permission_check.py": frozenset({"rest_framework.permissions"}),
    # The dual-base exceptions: each is the kernel's refusal and DRF's, so a view
    # that catches DRF's still catches it.
    "service_specs/drf_not_authenticated.py": frozenset({"rest_framework.exceptions"}),
    "service_specs/drf_service_validation_error.py": frozenset({"rest_framework.exceptions"}),
    "service_specs/drf_invalid_arguments.py": frozenset({"rest_framework.exceptions"}),
    "service_specs/drf_not_permitted.py": frozenset({"rest_framework.exceptions"}),
    "service_specs/drf_principal_unavailable.py": frozenset({"rest_framework.exceptions"}),
    "service_specs/register_drf_row_errors.py": frozenset({"rest_framework.exceptions"}),
    "service_specs/renderable_serializer_class.py": frozenset({"rest_framework.serializers"}),
    # The serializer is the spec's Presenter and Validator.
    "service_specs/serializer_presenter.py": frozenset(
        {"rest_framework.fields", "rest_framework.serializers"}
    ),
    # ``rest_framework.fields`` for ``get_error_detail``: a server value's field
    # is validated apart from the serializer's pass, and a Django refusal of it is
    # answered in the shape DRF's own field loop gives one.
    "service_specs/serializer_validator.py": frozenset(
        {"rest_framework.fields", "rest_framework.serializers"}
    ),
    "service_specs/translate_dispatch_errors.py": frozenset({"rest_framework.exceptions"}),
    # The reverse direction: an author's DRF refusals, raised as the kernel's classes.
    "service_specs/translate_drf_refusals.py": frozenset({"rest_framework.exceptions"}),
    # ``rest_framework`` and ``rest_framework.settings`` are read for the formats
    # DRF's own fields use (``ISO_8601`` and the date and time format settings), so
    # a value the adapter renders agrees with the one a serializer field renders in
    # the same API. Those are DRF's decision by definition.
    "service_specs/utils.py": frozenset(
        {
            "rest_framework",
            "rest_framework.relations",
            "rest_framework.serializers",
            "rest_framework.settings",
        }
    ),
}


def test_the_adapter_never_imports_the_http_views() -> None:
    found = _imports_matching(VIEWS_PREFIXES, edge=True)
    assert not found, (
        f"The adapter over the kernel imports the HTTP views: {found}. The views call "
        "the adapter, never the reverse."
    )


def test_no_new_import_of_drf_in_the_adapter() -> None:
    added = _difference(_imports_matching(DRF_PREFIXES, edge=True), ALLOWED_EDGE_DRF_IMPORTS)
    assert not added, (
        f"New imports of DRF in the adapter: {added}. Add them to "
        "ALLOWED_EDGE_DRF_IMPORTS with the reason beside each."
    )


def test_every_allowed_adapter_drf_import_still_exists() -> None:
    gone = _difference(ALLOWED_EDGE_DRF_IMPORTS, _imports_matching(DRF_PREFIXES, edge=True))
    assert not gone, (
        f"These allowed imports of DRF in the adapter no longer exist: {gone}. Remove "
        "them from ALLOWED_EDGE_DRF_IMPORTS."
    )


# Who may import the adapter. Only the DRF edge over the kernel's ``dispatch`` and its
# refusal map; nothing else outside the transport has a reason to.
ADAPTER_PREFIX = ("django_spec_rest.service_specs",)
ALLOWED_ADAPTER_IMPORTERS = frozenset(
    {
        # The kernel route: the seed-named fields it hands the body, the recording
        # twin it dispatches, and the edge's per-call state.
        "dispatch/kernel_edge.py",
        # The kernel route's refusal map: the dual-base twins it answers with.
        "dispatch/kernel_refusals.py",
    }
)


def test_only_the_edge_imports_the_adapter() -> None:
    found = set(_imports_matching(ADAPTER_PREFIX))
    assert found == ALLOWED_ADAPTER_IMPORTERS, (
        f"New importers of the adapter: {sorted(found - ALLOWED_ADAPTER_IMPORTERS)}; "
        f"gone: {sorted(ALLOWED_ADAPTER_IMPORTERS - found)}. Keep ALLOWED_ADAPTER_IMPORTERS "
        "to what really imports it."
    )


def test_the_adapter_never_imports_dispatch() -> None:
    found = _imports_matching(("django_spec_rest.dispatch",), edge=True)
    assert not found, (
        f"The adapter imports the dispatch edge: {found}. dispatch calls the adapter, "
        "never the reverse."
    )
