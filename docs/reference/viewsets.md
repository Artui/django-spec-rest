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

## The lookup capture

A router mounts `retrieve`, `update`, `partial_update`, `destroy` and every
`detail=True` action on the detail route, capturing the lookup under
`lookup_url_kwarg`, else `lookup_field` (`pk` by default), and hands
`as_view()` `detail=True`. A route capture reaches a spec only as a parameter it
declares, so on a router-mounted detail route `as_view()` refuses an action
whose row lookup does not declare the capture: the `retrieve` spec or a detail
`@selector_action`'s spec, or a write's `instance_selector_spec`, whose own
`reads` are all the kernel hands it. The refusal names the viewset, the action
and the capture. Declare the read under the capture's name, or point
`lookup_url_kwarg` at the name the selector reads:

```python
by_id = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, pk: Invoice.objects.get(pk=pk),
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
)
```

A list action, a `detail=False` action, and a write over a set
(`collection_selector_spec`) or a list body (`many=True`) look up no row and are
not asked. A viewset mounted by hand is not asked, nor is a standalone view:
their captures come from the URLconf, which `as_view()` cannot see. A singleton
such as `path("me/", MeViewSet.as_view({"get": "retrieve"}))`, whose selector
finds the caller's own row, carries no capture and needs no read; a hand-mounted
route that does carry one must have it declared by the selector itself.

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
