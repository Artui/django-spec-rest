# Viewsets

Every viewset here takes `pool_seeds`, the kernel `PoolSeeds` its specs'
callables are resolved with, as a class attribute or as
`as_view(actions, pool_seeds=...)`: the kernel's `DEFAULT_POOL_SEEDS` unless
set. `as_view()` checks each `action_specs` entry against it, one handed as
`as_view(actions, action_specs=...)` included, and every action,
a `@service_action` or `@selector_action` one included, dispatches with it. A
DRF viewset of your own serving a decorated action reads the same attribute
where it declares one. See
[Registering a seed](../recipes/extra-kwargs.md#registering-a-seed).

## Full CRUD

::: django_spec_rest.viewsets.service_viewset.ServiceViewSet

::: django_spec_rest.viewsets.selector_viewset.SelectorViewSet

## Per-action mixins

::: django_spec_rest.viewsets.service_create_mixin.ServiceCreateMixin

::: django_spec_rest.viewsets.service_update_mixin.ServiceUpdateMixin

::: django_spec_rest.viewsets.service_destroy_mixin.ServiceDestroyMixin

::: django_spec_rest.viewsets.selector_list_mixin.SelectorListMixin

::: django_spec_rest.viewsets.selector_retrieve_mixin.SelectorRetrieveMixin

## Action-serializer dispatch

::: django_spec_rest.viewsets.action_serializer_resolver.ActionSerializerResolver

## Custom actions

::: django_spec_rest.viewsets.decorators.service_action.service_action

::: django_spec_rest.viewsets.decorators.selector_action.selector_action
