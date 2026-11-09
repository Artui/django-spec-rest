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

A kernel dispatch a service makes for another principal runs under that
principal's offline request and view as well: neither the outer request nor the
view reaches its validation or the description of its serializer.

That holds when the service dispatches the view's own spec as well: the view's
serializer is described once for the request's own call, under its request and
view, and a dispatch the service makes of the same spec is described afresh,
the kernel telling the two apart by the `call_context` each call carries. A
service that hands its own `call_context` on to such a dispatch makes it the
request's call again, so pass it none, or a new dict.

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

## A selector reading `request.query_params` over MCP

`django-spec-mcp` knows no DRF: the `request` a spec's callables are handed there
is Django's `HttpRequest`, which has no `query_params`. Declaring the value in the
selector's `reads` makes it a tool argument, and is the better answer. A project
keeping a selector that reads the request itself registers its own `request` seed,
a DRF request built with
[`build_offline_context`][django_spec_rest.service_specs.build_offline_context.build_offline_context],
which is this package's, so `django-spec-mcp` has no equivalent:

```python
from django_service_specs import DEFAULT_POOL_SEEDS
from django_spec_mcp import MCPServer
from django_spec_rest import build_offline_context


def drf_request(*, user, request):
    return build_offline_context(user, http_request=request).request


server = MCPServer(pool_seeds=DEFAULT_POOL_SEEDS.extend(request=drf_request))
```

A registered `request` is the value at every stage of a tool's call and a kernel
resource's read, and its resolver is handed the call's own. The wrapped request
is a copy, with the principal as its `user`, so the call's own is untouched. Its
`query_params` are the query string of the MCP endpoint's `POST`, usually empty,
so a selector reading a value there falls to its default; pass `query_params=` to
`build_offline_context` for a value the project fixes.

**Not yet for a UI view.** A view resource, an MCP Apps UI resource among them,
holds a bare selector whose pool `django-spec-mcp` builds by spreading its own
`request` beside the server's seeds, and the kernel refuses the two with a
`TypeError` when one is read. The fix is in `django-spec-mcp` and is not released.
Until it is, keep this seed off a server serving view resources, and mount the
specs reading it on a server of their own.
