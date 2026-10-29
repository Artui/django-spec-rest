"""Every value and exception django-service-specs defines is drfs' too, by identity.

drfs keeps each name at its own module path, and the module re-exports the
kernel's object rather than defining a twin. Identity, not equality, is the
claim, because it is what a consumer meets first: an ``except ServiceError``
written against either package catches what the other raises, and an
``isinstance`` against a drfs relation spec answers for one the kernel built.

The behaviour of each object is the kernel's, and its tests are the kernel's.
What stays here is the one row per module that would fail if drfs defined the
name again, and, in the test file beside each module, the behaviour a drfs
caller sees change because the object did.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import django_service_specs
import pytest

import django_spec_rest

# (drfs module, kernel module, name). The kernel paths are the leaf modules
# the kernel pins for drfs, never its package root, so a move there fails here
# by name rather than resolving through a re-export.
REEXPORTS: list[tuple[str, str, str]] = [
    # Exceptions.
    (
        "django_spec_rest.exceptions.action_unavailable",
        "django_service_specs.services.action_unavailable",
        "ActionUnavailable",
    ),
    (
        "django_spec_rest.exceptions.additional_input_required",
        "django_service_specs.services.additional_input_required",
        "AdditionalInputRequired",
    ),
    (
        "django_spec_rest.exceptions.service_conflict",
        "django_service_specs.services.service_conflict",
        "ServiceConflict",
    ),
    (
        "django_spec_rest.exceptions.service_error",
        "django_service_specs.services.service_error",
        "ServiceError",
    ),
    (
        "django_spec_rest.exceptions.service_not_found",
        "django_service_specs.services.service_not_found",
        "ServiceNotFound",
    ),
    (
        "django_spec_rest.exceptions.service_validation_error",
        "django_service_specs.services.service_validation_error",
        "ServiceValidationError",
    ),
    # Values.
    (
        "django_spec_rest.types.audience_projection",
        "django_service_specs.output.audience_projection",
        "AudienceProjection",
    ),
    (
        "django_spec_rest.types.change_result",
        "django_service_specs.mutations.change_result",
        "ChangeResult",
    ),
    (
        "django_spec_rest.types.child_collection_change",
        "django_service_specs.mutations.child_collection_change",
        "ChildCollectionChange",
    ),
    (
        "django_spec_rest.types.field_audience",
        "django_service_specs.types.field_audience",
        "FieldAudience",
    ),
    (
        "django_spec_rest.types.field_change",
        "django_service_specs.mutations.field_change",
        "FieldChange",
    ),
    (
        "django_spec_rest.types.field_marking",
        "django_service_specs.output.field_marking",
        "FieldMarking",
    ),
    (
        "django_spec_rest.types.output_page",
        "django_service_specs.types.output_page",
        "OutputPage",
    ),
    (
        "django_spec_rest.types.progress_reporter",
        "django_service_specs.types.progress_reporter",
        "ProgressReporter",
    ),
    (
        "django_spec_rest.types.related_object_change",
        "django_service_specs.mutations.related_object_change",
        "RelatedObjectChange",
    ),
    (
        "django_spec_rest.types.relation_mode",
        "django_service_specs.types.relation_mode",
        "RelationMode",
    ),
    (
        "django_spec_rest.types.relation_orphan",
        "django_service_specs.types.relation_orphan",
        "RelationOrphan",
    ),
    (
        "django_spec_rest.types.relation_outcome",
        "django_service_specs.types.relation_outcome",
        "RelationOutcome",
    ),
    (
        "django_spec_rest.types.relation_phase",
        "django_service_specs.types.relation_phase",
        "RelationPhase",
    ),
    (
        "django_spec_rest.types.selector_kind",
        "django_service_specs.types.selector_kind",
        "SelectorKind",
    ),
    ("django_spec_rest.types.unset", "django_service_specs.types.unset", "UNSET"),
    ("django_spec_rest.types.unset", "django_service_specs.types.unset", "UnsetType"),
    (
        "django_spec_rest.types.affordance",
        "django_service_specs.types.affordance",
        "Affordance",
    ),
    (
        "django_spec_rest.types.value_formatter",
        "django_service_specs.types.value_formatter",
        "ValueFormatter",
    ),
    # The relation layer's declarations.
    (
        "django_spec_rest.types.child_spec",
        "django_service_specs.relations.child_spec",
        "ChildSpec",
    ),
    (
        "django_spec_rest.types.forward_relation_spec",
        "django_service_specs.relations.forward_relation_spec",
        "ForwardRelationSpec",
    ),
    (
        "django_spec_rest.types.generic_relation_spec",
        "django_service_specs.relations.generic_relation_spec",
        "GenericRelationSpec",
    ),
    (
        "django_spec_rest.types.many_to_many_spec",
        "django_service_specs.relations.many_to_many_spec",
        "ManyToManySpec",
    ),
    (
        "django_spec_rest.types.reverse_one_to_one_spec",
        "django_service_specs.relations.reverse_one_to_one_spec",
        "ReverseOneToOneSpec",
    ),
    (
        "django_spec_rest.types.relation_spec",
        "django_service_specs.relations.relation_spec",
        "RelationSpec",
    ),
    # The binding for a service with no body, and the answer a ``kwargs=``
    # provider reads to.
    (
        "django_spec_rest.types.no_input",
        "django_service_specs.types.no_input",
        "NoInput",
    ),
    (
        "django_spec_rest.types.provider_keys",
        "django_service_specs.types.provider_keys",
        "ProviderKeys",
    ),
    # The keyword pool's seed registry.
    (
        "django_spec_rest.types.pool_seeds",
        "django_service_specs.pool.pool_seeds",
        "PoolSeeds",
    ),
    (
        "django_spec_rest.types.pool_seeds",
        "django_service_specs.pool.pool_seeds",
        "DEFAULT_POOL_SEEDS",
    ),
    (
        "django_spec_rest.types.reserved_pool_seeds",
        "django_service_specs.pool.reserved_pool_seeds",
        "RESERVED_POOL_SEEDS",
    ),
    # What dispatch answers, and how it treats an argument nothing declares.
    (
        "django_spec_rest.types.dispatch_result",
        "django_service_specs.dispatch.dispatch_result",
        "DispatchResult",
    ),
    (
        "django_spec_rest.types.unknown_arguments",
        "django_service_specs.types.unknown_arguments",
        "UnknownArguments",
    ),
    # The registry a project declares its operations in once.
    (
        "django_spec_rest.types.registered_spec",
        "django_service_specs.registry.registered_spec",
        "RegisteredSpec",
    ),
    (
        "django_spec_rest.registry.spec_registry",
        "django_service_specs.registry.spec_registry",
        "SpecRegistry",
    ),
]


@pytest.mark.parametrize(
    ("drfs_module", "kernel_module", "name"),
    REEXPORTS,
    ids=[f"{row[0].rsplit('.', 1)[1]}.{row[2]}" for row in REEXPORTS],
)
def test_the_drfs_name_is_the_kernels_object(
    drfs_module: str, kernel_module: str, name: str
) -> None:
    drfs_object = getattr(importlib.import_module(drfs_module), name)
    kernel_object = getattr(importlib.import_module(kernel_module), name)

    assert drfs_object is kernel_object


# Every name of the package root's ``__all__`` that is the kernel's own object.
# The rows above pin one per drfs module at the kernel's leaf path; this set pins
# the whole root, so a drfs twin of any of them, or a new re-export, fails here.
# The other names of ``__all__`` are drfs' own, among them the views, the specs,
# the edge, and the wrappers over the kernel's (``enforce_affordances``,
# ``aenforce_affordances``, ``unmet_operation_affordance``,
# ``aunmet_operation_affordance``, ``audience_projection_for_spec`` and
# ``can_present_nothing``).
KERNEL_OWNED_ROOT_NAMES: frozenset[str] = frozenset(
    {
        "ActionUnavailable",
        "AdditionalInputRequired",
        "Affordance",
        "AsyncSelector",
        "AudienceProjection",
        "ChangeResult",
        "ChildCollectionChange",
        "ChildSpec",
        "CreateService",
        "DEFAULT_PAGE_SIZE",
        "DEFAULT_POOL_SEEDS",
        "DeleteService",
        "DispatchResult",
        "FieldAudience",
        "FieldChange",
        "FieldMarking",
        "ForwardRelationSpec",
        "GenericRelationSpec",
        "ListSelector",
        "ManyToManySpec",
        "NoInput",
        "OutputPage",
        "PoolSeeds",
        "ProgressReporter",
        "ProviderKeys",
        "RESERVED_POOL_SEEDS",
        "RegisteredSpec",
        "RelatedObjectChange",
        "RelationMode",
        "RelationOrphan",
        "RelationOutcome",
        "RelationPhase",
        "RelationSpec",
        "RetrieveSelector",
        "ReverseOneToOneSpec",
        "Selector",
        "SelectorKind",
        "ServiceConflict",
        "ServiceError",
        "ServiceNotFound",
        "ServiceValidationError",
        "SpecRegistry",
        "UNSET",
        "UnknownArguments",
        "UnsetType",
        "UpdateService",
        "ValueFormatter",
        "acreate_from_input",
        "acreate_model",
        "adelete_collection",
        "adelete_model",
        "amaterialize_retrieve",
        "annotate_output_schema",
        "apply_input",
        "arun_selector",
        "arun_service",
        "aupdate_from_input",
        "aupdate_model",
        "base_pool",
        "combine_progress",
        "create_from_input",
        "create_model",
        "delete_collection",
        "delete_model",
        "implements",
        "is_async",
        "is_queryset",
        "materialize_retrieve",
        "null_progress",
        "operation_affordances",
        "paginate_output",
        "project_payload",
        "provider_keys",
        "run_selector",
        "run_service",
        "update_from_input",
        "update_model",
    }
)


def _kernel_objects_by_name() -> dict[str, list[object]]:
    """Every value each importable kernel module holds, by the name it holds it under.

    The pydantic adapter imports an optional dependency this suite does not
    install, and defines nothing drfs re-exports, so a module that cannot be
    imported is passed over.
    """
    found: dict[str, list[object]] = {}
    for module_info in pkgutil.walk_packages(
        django_service_specs.__path__, "django_service_specs."
    ):
        try:
            module = importlib.import_module(module_info.name)
        except ImportError:
            continue
        for name, value in vars(module).items():
            found.setdefault(name, []).append(value)
    return found


def test_the_roots_kernel_objects_are_exactly_these() -> None:
    """Identity, by name, against every kernel module. ``DEFAULT_PAGE_SIZE`` is a
    small ``int``, which CPython interns, so its identity proves nothing: the
    module that re-exports it is held to importing it from the kernel instead."""
    kernel = _kernel_objects_by_name()
    owned = {
        name
        for name in django_spec_rest.__all__
        if any(value is getattr(django_spec_rest, name) for value in kernel.get(name, []))
    }

    assert owned == KERNEL_OWNED_ROOT_NAMES
    assert len(KERNEL_OWNED_ROOT_NAMES) == 77
    source = inspect.getsource(importlib.import_module("django_spec_rest.dispatch.paginate_output"))
    assert "from django_service_specs.dispatch.paginate_output import DEFAULT_PAGE_SIZE" in source
