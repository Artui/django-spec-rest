"""The stable dispatch surface: blessed top-level re-exports.

Stable since 0.17: the dispatch leaves alternate transports build on are part
of the documented public API. This test pins the contract: every blessed
symbol is importable from the top-level package and is *the same object*
as its leaf-module home (no divergent copies). The private ``_compat``
package was removed in the same release — downstreams re-point their
imports here when they bump past 0.17.
"""

from __future__ import annotations

import django_spec_rest as pkg
from django_spec_rest.can_present_nothing import can_present_nothing
from django_spec_rest.dispatch.adispatch_spec import adispatch_spec
from django_spec_rest.dispatch.aenforce_affordances import aenforce_affordances
from django_spec_rest.dispatch.aunmet_operation_affordance import (
    aunmet_operation_affordance,
)
from django_spec_rest.dispatch.build_offline_context import build_offline_context
from django_spec_rest.dispatch.dispatch_spec import dispatch_spec
from django_spec_rest.dispatch.enforce_affordances import enforce_affordances
from django_spec_rest.dispatch.enforce_permissions import enforce_permissions
from django_spec_rest.dispatch.operation_affordances import operation_affordances
from django_spec_rest.dispatch.provider_keys import provider_keys
from django_spec_rest.dispatch.render_spec_output import render_spec_output
from django_spec_rest.dispatch.renderable_serializer_class import renderable_serializer_class
from django_spec_rest.dispatch.unmet_operation_affordance import (
    unmet_operation_affordance,
)
from django_spec_rest.dispatch.utils import server_owned_keys
from django_spec_rest.is_async import is_async
from django_spec_rest.jsonschema.filterset_to_json_schema import filterset_to_json_schema
from django_spec_rest.jsonschema.output_to_json_schema import output_to_json_schema
from django_spec_rest.jsonschema.serializer_to_json_schema import serializer_to_json_schema
from django_spec_rest.jsonschema.spec_to_json_schema import spec_to_json_schema
from django_spec_rest.registry.capability_manifest import capability_manifest
from django_spec_rest.registry.spec_registry import SpecRegistry
from django_spec_rest.selectors.utils import (
    amaterialize_retrieve,
    apply_queryset_shaping,
    arun_selector,
    is_queryset,
    materialize_retrieve,
    run_selector,
)
from django_spec_rest.services.arun_service import arun_service
from django_spec_rest.services.run_service import run_service
from django_spec_rest.types.provider_keys import ProviderKeys
from django_spec_rest.types.registered_spec import RegisteredSpec
from django_spec_rest.types.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_spec_rest.views.mutation.utils import (
    build_input_serializer,
    build_input_serializer_from_data,
    resolve_mutation_instance,
    validate_input,
)
from django_spec_rest.views.utils import resolve_callable_kwargs

# Blessed name → the leaf-module original it must alias.
_SURFACE = {
    # What ``provider_keys`` answers, so a transport can annotate the value it
    # holds without importing from a leaf module.
    "ProviderKeys": ProviderKeys,
    # Adapters are told to import this rather than keep a copy of the seed
    # names, so it has to be reachable from the same place as the rest of
    # the dispatch surface.
    "RESERVED_POOL_SEEDS": RESERVED_POOL_SEEDS,
    "RegisteredSpec": RegisteredSpec,
    "SpecRegistry": SpecRegistry,
    "adispatch_spec": adispatch_spec,
    # A transport that runs a service without the dispatch core -- a chain step --
    # re-runs the affordance check through these, as it re-runs permissions.
    "aenforce_affordances": aenforce_affordances,
    # A transport that runs a ``RETRIEVE`` selector without the dispatch core
    # collapses its return through these, or its object-level permissions judge a
    # queryset and skip ``has_object_permission``.
    "amaterialize_retrieve": amaterialize_retrieve,
    "apply_queryset_shaping": apply_queryset_shaping,
    "arun_selector": arun_selector,
    "arun_service": arun_service,
    # A transport deciding which operations to offer -- a tool list, an agent's
    # toolset -- asks these, rather than re-deriving which names a condition sees.
    "aunmet_operation_affordance": aunmet_operation_affordance,
    "build_input_serializer": build_input_serializer,
    "build_input_serializer_from_data": build_input_serializer_from_data,
    "build_offline_context": build_offline_context,
    # A transport advertising an output schema of its own asks this whether
    # dispatch may present ``None``, rather than deriving the ``null`` again.
    "can_present_nothing": can_present_nothing,
    "capability_manifest": capability_manifest,
    "dispatch_spec": dispatch_spec,
    "enforce_affordances": enforce_affordances,
    "enforce_permissions": enforce_permissions,
    "filterset_to_json_schema": filterset_to_json_schema,
    "is_async": is_async,
    "is_queryset": is_queryset,
    "materialize_retrieve": materialize_retrieve,
    # A transport skips building a pool or taking a thread hop for an operation
    # with nothing to ask at list time by reading this, rather than re-deriving
    # which conditions are answered without a row.
    "operation_affordances": operation_affordances,
    "output_to_json_schema": output_to_json_schema,
    # A transport building a schema or refusing a call reads which names a
    # ``kwargs=`` provider fills through this, rather than keeping a copy of the
    # reader, as both spec transports once did.
    "provider_keys": provider_keys,
    "render_spec_output": render_spec_output,
    # A transport that renders an output declaration outside ``render_spec_output``
    # resolves the class through this, or a dataclass output raises there.
    "renderable_serializer_class": renderable_serializer_class,
    "resolve_callable_kwargs": resolve_callable_kwargs,
    "resolve_mutation_instance": resolve_mutation_instance,
    "run_selector": run_selector,
    "run_service": run_service,
    "serializer_to_json_schema": serializer_to_json_schema,
    # A transport building an input schema of its own -- a service tool merging its
    # target lookup's keys -- subtracts this, the set dispatch strips, rather than
    # reading each callable's markers again and missing the ones another hides.
    "server_owned_keys": server_owned_keys,
    "spec_to_json_schema": spec_to_json_schema,
    "unmet_operation_affordance": unmet_operation_affordance,
    "validate_input": validate_input,
}


def test_every_blessed_symbol_is_a_top_level_export() -> None:
    for name, original in _SURFACE.items():
        assert name in pkg.__all__, f"{name} missing from __all__"
        assert getattr(pkg, name) is original, f"{name} diverged from its leaf module"


def test_the_compat_package_is_gone() -> None:
    # Removed in 0.17 — anything still importing it should fail loudly here
    # rather than in a downstream release.
    import importlib.util

    assert importlib.util.find_spec("django_spec_rest._compat") is None


def test_no_export_is_shadowed_by_its_own_submodule() -> None:
    """Every re-exported name resolves to a value, never to a module object.

    **This hazard is real and has already been hit once.** ``import pkg.mod``
    binds ``mod`` as an attribute of ``pkg``, so a package ``__init__`` that
    does ``from pkg.mod import mod`` (function and module sharing a name — the
    one-symbol-per-file convention makes that the *normal* case here) can have
    its function binding overwritten by the submodule, if some *other* import
    on a later line pulls ``pkg.mod`` in for the first time. The symptom is a
    module where a callable was expected, at import time, far from the edit
    that caused it.

    ``dispatch/__init__.py`` carries a hand-written comment pinning one such
    ordering. ⇒ *an invariant maintained by a comment is maintained until
    someone sorts the imports.* This asserts it for every export in every
    package instead, so a future reordering fails here rather than downstream.
    """
    import importlib
    from types import ModuleType

    packages = [
        "django_spec_rest",
        "django_spec_rest.dispatch",
        "django_spec_rest.mutations",
        "django_spec_rest.selectors",
        "django_spec_rest.services",
        "django_spec_rest.types",
    ]
    shadowed: list[str] = []
    for name in packages:
        module = importlib.import_module(name)
        for export in getattr(module, "__all__", ()):
            if isinstance(getattr(module, export), ModuleType):
                shadowed.append(f"{name}.{export}")
    assert shadowed == []
