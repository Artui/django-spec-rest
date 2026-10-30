# Reference

Autodocumented public API. Every page reads the docstrings and signatures
from the source.

A spec itself, and everything the kernel owns (`ServiceSpec`, `SelectorSpec`,
`Parameter`, `Parameters`, `SelectorKind`, the refusals, `dispatch`), is
imported from [`django_service_specs`](https://artui.github.io/django-service-specs/)
and documented there. This package documents what it adds over DRF.

- **[Views](views.md)**: `ServiceCreateView`, `ServiceUpdateView`,
  `ServiceDeleteView`, `SelectorListView`, `SelectorRetrieveView`,
  `MutationFlowMixin`, `resolve_mutation_instance`.
- **[Viewsets](viewsets.md)**: `ServiceViewSet`, `SelectorViewSet`, the
  per-action mixins, `ActionSerializerResolver`, `@service_action`,
  `@selector_action`.
- **[DRF seats](service-specs.md)**: `SerializerValidator`,
  `SerializerPresenter`, `DRFPermissionCheck`, the DRF refusal classes and the
  translators between the kernel's refusals and DRF's, and the offline context.
- **[Types](types.md)**: `ServiceView`, `ViewHooks`, `HttpExtras`, the offline
  request and view, `MARKING` and the JSON Schema registry.
- **[OpenAPI](openapi.md)**: `enable_openapi`, `ServiceAutoSchema`,
  `ServiceErrorSerializer` (the opt-in `drf-spectacular` adapter).

## Public surface

The top-level `django_spec_rest` package exports the 29 names below. The
subpackages `django_spec_rest.views`, `django_spec_rest.viewsets`,
`django_spec_rest.types` and `django_spec_rest.openapi` export theirs from
their `__init__`, and the seat adapters are imported from their leaf modules
under `django_spec_rest.service_specs`, as the [DRF seats](service-specs.md)
page shows.

| Group | Names |
| --- | --- |
| Views | `ServiceCreateView`, `ServiceUpdateView`, `ServiceDeleteView`, `SelectorListView`, `SelectorRetrieveView`, `MutationFlowMixin`, `resolve_mutation_instance` |
| Viewsets | `ServiceViewSet`, `SelectorViewSet`, `ServiceCreateMixin`, `ServiceUpdateMixin`, `ServiceDestroyMixin`, `SelectorListMixin`, `SelectorRetrieveMixin`, `ActionSerializerResolver`, `service_action`, `selector_action` |
| Types | `ServiceView`, `ViewHooks`, `HttpExtras`, `OfflineContext`, `OfflineHttpRequest`, `OfflineServiceView`, `MARKING`, `JsonSchemaRegistry`, `DEFAULT_JSON_SCHEMA_REGISTRY` |
| Serializer helpers | `base_serializer_context`, `build_offline_context`, `renderable_serializer_class` |
