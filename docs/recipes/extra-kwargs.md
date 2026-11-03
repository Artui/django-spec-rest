# View hooks and providers

A service is handed the keywords it declares: the kernel's seeds (`user`,
`data`, `instance`, `request`, `view`, ...), the spec's arguments, and the
values the server adds. The server adds them in two places: on the spec, which
every transport serving it runs, and on the view, which only HTTP runs.

## On the spec: providers

A `kwargs` provider returns extra keywords for the service; an `input_data`
provider returns values merged into the input before the serializer validates
it. Either declares the seeds it reads: `user` is the principal on every
transport, and over HTTP `request` and `view` are the call's.

```python
from django_service_specs import ServiceSpec


def tenant_kwargs(*, user):
    return {"tenant": user.tenant}


CREATE_SPEC = ServiceSpec(
    service=create_note,  # def create_note(*, data, tenant): ...
    validator=SerializerValidator(NoteInput),
    kwargs=tenant_kwargs,
    permissions=OPEN,
)
```

A `kwargs` provider may not return a key a validator field declares: its
value would reach the service unvalidated. A typed provider (one whose return
annotation is a `TypedDict`) naming such a key is refused when the view is
built, and an untyped one on the request whose answer names it. Return the
value from `input_data=` instead, where the serializer validates it. A key
named like a field's `source` stays the provider's.

A provider is server code, and its values reach the callable as returned: a
provider's `"abc"` for an `x: int` parameter is not coerced.

## Registering a seed

A fact every callable may need and no argument carries (a tenant, a feature
flag, a "sending is paused" switch) is a seed: register a resolver for it on
a `PoolSeeds` and set that registry on the view's `pool_seeds`, as a class
attribute or as `as_view(pool_seeds=...)`. Any callable of the spec declaring
the seed's name is handed its value: the service and its selectors, the
providers, a permission check, a precondition and an affordance condition.

```python
from django_service_specs import DEFAULT_POOL_SEEDS, Affordance, ServiceSpec

from django_spec_rest import ServiceViewSet

SEEDS = DEFAULT_POOL_SEEDS.extend(frozen=board_is_frozen)

RENAME_SPEC = ServiceSpec(
    service=rename_task,
    instance_selector_spec=TASK_BY_PK,
    affordances=[
        Affordance(
            code="board_frozen", reason="The board is frozen.", when=lambda *, frozen: not frozen
        ),
    ],
    permissions=OPEN,
)


class TaskViewSet(ServiceViewSet):
    pool_seeds = SEEDS
    action_specs = {"partial_update": RENAME_SPEC}
```

Build the registry once, at import: the view checks its spec against it at
`as_view()` and hands that one object to every call. A view that does not
register a seed one of its spec's callables requires refuses the spec at
`as_view()`, naming the seed, rather than failing every request. A
`@service_action` or `@selector_action` spec is checked by its viewset's
`as_view()`, against the viewset's `pool_seeds`, as an `action_specs` entry
is, so a seed the viewset registers serves and one it does not is refused
there. A `@service_action` on a viewset overriding `get_service_kwargs` or
`get_<action>_service_kwargs` is not asked, since the hook may fill what the
check would refuse. Each seed a
permission check names is resolved once per call, its value handed from the
check to the run. The OpenAPI request body and the `OPTIONS` answer read the
same registry: a read a registered seed fills is no key a caller is asked to
send, and `OPTIONS` asks a permission check naming a registered seed.
The decorated action's check is made by this package's viewsets
(`ServiceViewSet`, `SelectorViewSet` or a class built on their mixins or
`ActionSerializerResolver`). On DRF's own `GenericViewSet` or `ViewSet`
nothing asks it, so a seed nobody registers is the action's first request's
`TypeError`.

## On the view: hooks

A mutation view or viewset has three hook chains, view-wide then per action,
the more specific winning on a key both return, and the spec's provider over
both:

| Hook | Feeds |
| --- | --- |
| `get_service_kwargs()`, `get_<action>_service_kwargs()` | the service's keywords |
| `get_input_data(request)`, `get_<action>_input_data()` | the input, before validation |
| `get_input_serializer_context()`, `get_<action>_input_serializer_context()` | the input serializer's `context` |

```python
from django_spec_rest import ServiceViewSet


class NoteViewSet(ServiceViewSet):
    action_specs = {"create": CREATE_SPEC}

    def get_service_kwargs(self):
        return {"owner": self.request.user}
```

**A hook's value outranks the client's.** Where the serializer declares a
writable `owner`, the hook's value is what reaches the service, so a client
sending `owner` cannot replace the hook's. A key a `validate()` derives, or a
`source="*"` nested serializer flattens, reaches the service's keyword as the
hook's value, while `data` keeps what the serializer validated.

A selector view takes no keyword hook beside a kernel spec: `as_view()`
refuses a `get_selector_kwargs` or `get_<action>_selector_kwargs` override,
which would never reach the spec. Return those keys from the spec's `kwargs`
provider.

Prefer the spec's providers for anything the operation needs wherever it is
served: a hook runs over HTTP only, and the same spec dispatched through the
kernel's `dispatch`, or served on another transport, never asks it.
