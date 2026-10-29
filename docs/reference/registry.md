# Spec registry

A named, taggable home for a project's spec set, so each transport reads one
source instead of enumerating the same specs again. Every symbol here is
importable from the top-level package.

For the task-shaped walkthrough — where the instance lives, multiple registries,
filtered views — see the recipe
[Declare specs once, project them to many transports](../recipes/spec-registry.md).

## `SpecRegistry`

::: django_spec_rest.registry.spec_registry.SpecRegistry

## `RegisteredSpec`

::: django_spec_rest.types.registered_spec.RegisteredSpec

## `capability_manifest`

::: django_spec_rest.registry.capability_manifest.capability_manifest

## `OfflineContract`

::: django_spec_rest.types.offline_contract.OfflineContract
