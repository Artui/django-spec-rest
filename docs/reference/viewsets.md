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

The schema documents a declared capture with the read's type and `help` where
drf-spectacular finds no model to type it from, as on a viewset with no
`queryset` (see [OpenAPI](../openapi.md#what-a-route-documents)).

## The row-scoping warning

A spec's rows are its selector's, so a `get_queryset()` override does not scope
them, and tenant scoping left in one lets a `PATCH` or `DELETE` reach another
tenant's row, and a `GET` read it, with no error. `as_view()` reports a viewset
that overrides it beside any spec (a write, a list or a retrieve) with a
`GetQuerysetScopeWarning` whose text begins with the stable id
**`django_spec_rest.W001`** and names the class:

```text
django_spec_rest.W001: myapp.views.InvoiceViewSet overrides get_queryset() (on InvoiceViewSet) and serves a spec, ...
```

An override counts on any class below this package's bases and DRF's, a mixin
listed after them included, since its `super()` runs. A spec counts under
`action_specs`, an `as_view(action_specs=...)` included, and under
`@service_action` or `@selector_action`, whatever its kind: a viewset serving
only a `retrieve` spec is reported as one serving a write or a list is. A
viewset with no override, or serving only actions with no spec, is not
reported (those take their rows from `get_queryset()`), and neither is a
backend in `filter_backends`, since most are plain list filters
([Moving from djangorestframework-services](../moving-from-drfs.md#views-and-viewsets)
says what changes for one that scoped a tenant).

The warning's `file:line` is the line that called `as_view()`. A viewset
mounted by hand is reported at your `urls.py` line. One mounted through a
router is reported at DRF's `rest_framework/routers.py`, which is where the
router calls `as_view()`, so read the class the text names rather than the
location.

An override can be right to stay: DRF's `DjangoModelPermissions` asks
`get_queryset()` for the model it checks. Once each selector scopes its own
rows, say so on the class:

```python
class InvoiceViewSet(ServiceViewSet):
    action_specs = {"list": INVOICES, "destroy": DELETE_INVOICE}
    spec_rows_scoped_by_selector = True

    def get_queryset(self) -> QuerySet[Invoice]:
        return Invoice.objects.all()
```

The attribute is inherited, so a base class says it once for its own override.
It covers only overrides on the class declaring it and that class's bases: one
a subclass adds, or a mixin listed before it, is reported again, because nobody
has yet said it scopes nothing. A subclass may set it to `False`.

It is a Python warning at `as_view()`, not a system check: this package has no
app config for a check to register on, and asks for no `INSTALLED_APPS` entry,
so `SILENCED_SYSTEM_CHECKS` does not apply. It prints when the URLconf is
imported, `manage.py check` included. Under Python's default filter a router
shows it once for a class, however many routes it mounts, and a class mounted
by hand shows it once per line mounting it. No request makes one. A project or a test suite may filter on the id, to fail on it say:

```python
warnings.filterwarnings("error", message=r"django_spec_rest\.W001")
```

A viewset of DRF's alone, serving `@service_action` or `@selector_action` with
no base of this package's, has no such `as_view()` and is not reported, and
neither is a standalone view.

::: django_spec_rest.viewsets.get_queryset_scope_warning.GetQuerysetScopeWarning

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

## One URL, several specs

One spec per route or action stays the default. An endpoint that must keep one
URL while the request chooses what runs takes a
[`DiscriminatedAction`](types.md#discriminated-actions): a `discriminator`
answering a key, and `specs` mapping each key to the kernel `ServiceSpec` serving
it. It is an `action_specs` entry under `create`, `update`, `partial_update` or
`destroy`, or the spec of a `@service_action`; `as_view()` refuses it under any
other action (`list`, `retrieve` or a custom one's name), on a `SelectorViewSet`, and as a
standalone view's `spec`, each refusal saying where it goes.

```python
INTAKE = DiscriminatedAction(
    discriminator=lambda *, data: "draft" if "amount_cents" in data else "blank",
    specs={"draft": CREATE_SPEC, "blank": BLANK_SPEC},
)


class IntakeViewSet(ServiceViewSet):
    action_specs = {"create": INTAKE}
```

(`examples/invoices` serves this as `POST /intake/` and asserts it over HTTP and
in the schema.) The discriminator is a sync callable declaring any of `request`,
`data` (the raw `request.data`), `user`, `view` and `call_context`, or `**kwargs`,
which is handed all but the last. An answer that is no key of `specs` is the
author's mistake: a 500 naming the keys.

Each variant is asked what a plain entry of that action is asked (its seeds, its
lookup capture, its answers), and the chosen one runs as a plain entry would, its
own checks deciding. So:

- **A caller every variant refuses** is refused before the body is read and
  before the discriminator runs, the first variant's denial answered: a 401 with
  the authenticator's challenge where nobody signed in, otherwise a 403. A caller
  some variant admits reaches the discriminator, and the chosen variant's checks
  then decide.
- **The row** is the chosen variant's own target selector's, as for any update or
  destroy.
- **Validation is the variant's.** A `PATCH` on the router's update route
  (an `update` or `partial_update` entry) is validated partially, as for a plain
  spec. A `@service_action` `PATCH` runs the chosen variant as declared, so it is
  validated whole; a variant declaring `partial` is the way to a partial call
  there.
- **A callable `success_status` or `response_finalizer`** on such an action may
  declare `variant`, the chosen key, to answer per variant
  ([Per-action answers](#per-action-answers)).

It is this transport's alone and never a kernel spec: `as_kernel_spec()` raises,
and an agent or an MCP client registers each variant on its own. The OpenAPI
schema documents the action as one request component over every variant's body
(see [OpenAPI](../openapi.md#what-a-route-documents)).

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
