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

## Per-action answers

A kernel spec declares no HTTP answer, so a viewset's `success_status` and
`response_finalizer` answer for every action it serves. An action that answers
differently declares its own, and the most specific one answers:

1. `@service_action(spec, success_status=..., response_finalizer=...)`, for a
   decorated action;
2. a `get_<action>_success_status` or `get_<action>_response_finalizer` hook on
   the viewset, for any action, an `action_specs` entry included;
3. the viewset's own, an `as_view(success_status=...)` keyword over the class
   attribute;
4. the action's default: 201 create, 200 update, 204 destroy, 200 a custom
   action.

```python
class MembershipViewSet(ServiceViewSet):
    action_specs = {"create": JOIN_SPEC, "destroy": LEAVE_SPEC}

    def get_create_success_status(self, *, result: Membership) -> int:
        return 201 if result.is_new else 200

    get_destroy_success_status = 200

    @service_action(CANCEL_SPEC, detail=True, methods=["post"], success_status=204)
    def cancel(self, request: Any, pk: Any = None) -> None:
        """Cancel a pending membership."""
```

Each takes the shapes the viewset's does. A status is an `int` or a callable
declaring any of `result`, `instance`, `request` and `view`; a finalizer is a
callable declaring any of `response`, `result`, `request`, `view`, `instance`
and `data`. A hook method is that callable, its `self` the view (a
`staticmethod` takes none), and an `int` attribute is the status. A hook is named for the action DRF names, as
`get_<action>_service_kwargs` is: a `PATCH` reads `get_partial_update_...`,
never `get_update_...`.

`as_view()` asks each per-action value what it asks the viewset's, naming the
action: a callable requiring a name the view cannot supply is refused, and so
is a decorator value beside a hook for the same action. That refusal is
this package's viewsets' `as_view()`: on a viewset of DRF's alone the
decorator's value answers and the hook is never read. The decorator's own
values are asked when it runs. The OpenAPI schema documents the status of the
action, where it is an `int`; a callable documents the action's default.

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
