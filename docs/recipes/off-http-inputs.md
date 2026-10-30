# Calling a spec off HTTP

A spec served on a route is the kernel's, so the kernel's `dispatch` runs it
with no request: from a management command, a task, a test, or another
transport serving kernel specs.

```python
from django_service_specs import dispatch

result = dispatch(
    UPDATE_SPEC,
    principal=user,
    arguments={"pk": invoice.pk, "customer": "Acme Ltd", "amount_cents": 4200},
)
result.value  # what the service returned
```

## Arguments in place of a request

There is no route, query string or body: `arguments` holds every value the
spec declares. A value the route would have captured, such as the `pk` a
target selector reads, is an argument like any other. A key no parameter
declares is refused under the kernel's default, where the HTTP edge drops it.

The input is validated as declared: the kernel checks the arguments' types,
then the `SerializerValidator`'s serializer validates them. Nothing is partial
unless the spec declares `partial=True`; a `PATCH` route's partial validation
is the route's.

## What runs and what does not

- **The spec's own seats run**: its providers, permissions, preconditions,
  validator and service. `result.value` is what the service returned; the
  kernel's `present` renders it through the spec's presenter.
- **The view does not**: its `permission_classes`, its hooks
  (`get_service_kwargs`, `get_input_data`, the serializer context hooks),
  `success_status` and `response_finalizer` belong to the route. Put what the
  operation needs everywhere on the spec.

## DRF's seats without a request

- **`DRFPermissionCheck`** asks its classes against an offline request and view
  built for the principal; see
  [DRF permission classes](permissions.md#off-http).
- **A serializer's context** is built over the same offline pair, so
  `self.context["request"].user` is the principal; see
  [Serializer context](serializer-context.md#off-http).
- **A refusal** is the kernel's class: `DRFNotPermitted`,
  `DRFInvalidArguments` and the other DRF refusal classes subclass the
  kernel's, so `except NotPermitted` catches a DRF permission class's refusal.

The example project dispatches its update spec and its permission-checked
send spec this way.
