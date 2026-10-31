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
