# Concepts

A view or viewset here serves a kernel spec. This page is what happens between
the request and the spec: which views take which specs, what the edge reads
from the request, how the input is validated, and how each answer and refusal
goes back as DRF's. What a spec itself declares is the
[kernel's documentation](https://artui.github.io/django-service-specs/).

## Views and the specs they take

| View | Spec on `spec` | Methods |
| --- | --- | --- |
| `ServiceCreateView` | `ServiceSpec` | `POST` |
| `ServiceUpdateView` | `ServiceSpec` with a target | `PUT`, `PATCH` |
| `ServiceDeleteView` | `ServiceSpec` with a target | `DELETE` |
| `SelectorListView` | `SelectorSpec(kind=SelectorKind.LIST)` | `GET` |
| `SelectorRetrieveView` | `SelectorSpec(kind=SelectorKind.RETRIEVE)` | `GET` |

`ServiceViewSet` takes one spec per action in `action_specs` (`list`,
`retrieve`, `create`, `update`, `partial_update`, `destroy`), and
`SelectorViewSet` its `list` and `retrieve`; `PATCH` falls back to `update`'s
spec. A custom route takes its
spec through `@service_action(spec)` or `@selector_action(spec)`. See
[Viewsets and custom actions](recipes/service-action.md).

`as_view()` checks the spec before the view serves anything: a spec of the
kind the view does not serve, an update or delete with no target, a
`filter_set` beside `DjangoFilterBackend`, and what the kernel's seed check
refuses of the callables' signatures, against the seeds the view registers on
`pool_seeds`, are each an `ImproperlyConfigured` at import. The specs of
`@service_action` and `@selector_action` are seed-checked by their viewset's
`as_view()`; on DRF's own `GenericViewSet` or `ViewSet`, with no base of this
package's, they are not, and a missing seed is the first request's
`TypeError`. A nested selector declaring `permissions` is refused by the kernel
when the `ServiceSpec` is built, not at `as_view()`. See
[Registering a seed](recipes/extra-kwargs.md#registering-a-seed).

A spec handed to `as_view(spec=...)` is checked and served exactly as the same
class attribute is, and so is every other keyword the checks read
(`pool_seeds`, `success_status`, `response_finalizer`, `filter_backends`): DRF
sets each on the instance, which outranks the class. A viewset's specs are its
`action_specs`, so `as_view(actions, action_specs=...)` is checked the same way;
a viewset declares no `spec`, and DRF refuses that keyword with a `TypeError`.

## What the edge reads from a request

The view turns the request into the one dict of arguments the kernel's
`dispatch` takes, and the principal into `request.user`:

- **Route captures** the spec declares as parameters (`reads`, or a target
  selector's `reads`) are arguments, coerced to their declared type and taken
  over anything the body or the query string sends for the same name. A
  capture the spec does not declare is no argument; it stays on
  `view.kwargs` for DRF.
- **The query string** is read by the kernel's flat reader: a blank value is
  absent, a typed array or a multiple-choice filter splits on a comma, and
  each value is coerced to its parameter's type.
- **A JSON body** is read as it was sent, and checked against the declared
  types as sent: a JSON `"true"` is a string, not a boolean. A view's
  `lenient_json_body`, or the project's `SPEC_REST_LENIENT_JSON_BODY`, has its
  serializer alone answer one instead, as DRF does; the spec stays typed.
- **A form body** is read as DRF reads one: `"on"` and a blank checkbox for a
  boolean, and the prefixed spellings `v.tenant` and `tags[0]` of a nested or
  list field.
- **A key no parameter declares is dropped**, as DRF's serializer drops one.

A write's target is its spec's own: `instance_selector_spec` for one row,
`collection_selector_spec` for a set. Its reads and its `filter_set` come from
the route and the query string, never the body, so a body value cannot choose
the row a write changes. A miss answers 404.

## Validation

A spec's `SerializerValidator` declares the serializer's writable fields as the
spec's parameters. The kernel checks the arguments against them first (a
missing required field and a mistyped one are refused together), then the
serializer validates the body it was bound to: its field validators,
`validate_<field>()` and `validate()`. The validated data reaches the service
as `data`.

`PATCH` validates only the fields sent. A spec declaring `partial=True`
validates `PUT` partially too.

### Bulk writes

A spec declaring `many=True` takes a JSON list of rows, each validated by its
`SerializerValidator`, and the service is handed the validated rows as `data`,
a list. A row that fails is refused at the index it was sent at, under the
spec's `many_argument` (`items` by default), every failing row in one 400, and
the service never runs:

```python
from django_service_specs import ServiceSpec, Unrestricted
from rest_framework import serializers

from django_spec_rest import ServiceCreateView
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from lines.models import Line


def create_lines(*, data):
    return [Line.objects.create(**row) for row in data]


class LineIn(serializers.Serializer):
    sku = serializers.CharField()
    quantity = serializers.IntegerField()


class LinesCreateView(ServiceCreateView):
    spec = ServiceSpec(
        service=create_lines,
        permissions=(Unrestricted(),),
        validator=SerializerValidator(LineIn),
        many=True,
    )
```

```http
POST /lines/
[{"sku": "a", "quantity": 1}, {"sku": "", "quantity": 1},
 {"sku": "a", "quantity": 1}, {"sku": "", "quantity": 1}]

400 Bad Request
{"items": {"1": {"sku": ["This field may not be blank."]},
           "3": {"sku": ["This field may not be blank."]}}}
```

A body that is no list is refused as a whole, `{"items": ["Expected an
array."]}`, and so is a list longer than the spec's `many_max_length`, else the
kernel's `SERVICE_SPECS_MAX_ARRAY_LENGTH` (1000 by default), with a 400 under
`items`. A view taking longer lists declares `many_max_length` on its spec.

## Hooks and providers

Three layers feed a write beyond the client's body, the more specific winning
on an overlapping key:

| Seat | View-wide | Per action (viewsets) | On the spec |
| --- | --- | --- | --- |
| Extra service keywords | `get_service_kwargs()` | `get_<action>_service_kwargs()` | `kwargs=` provider |
| Extra serializer input | `get_input_data(request)` | `get_<action>_input_data()` | `input_data=` provider |
| Input serializer context | `get_serializer_context()`, then `get_input_serializer_context()` | `get_<action>_input_serializer_context()` | `SerializerValidator(serializer_context=)` |
| Output serializer context | `get_serializer_context()`, then `get_output_serializer_context()` | `get_<action>_output_serializer_context()` | `SerializerPresenter(serializer_context=)` |

A view hook's value outranks the validated value, so a hook returning
`{"owner": request.user}` cannot be overwritten by a client sending `owner`. A
`kwargs` provider may not return a key a validator field declares; pass such a
value through `input_data=`, where the serializer validates it. A selector
view takes no keyword hook beside a kernel spec: `as_view()` refuses a
`get_selector_kwargs` override, and the spec's own `kwargs` provider fills its
keywords. See [View hooks and providers](recipes/extra-kwargs.md).

## Answers

A spec's `presenter` renders the result. A list view paginates with the view's
paginator and presents the page's rows; a list or retrieve spec declaring
neither a presenter nor affordances is rendered by the view's
`serializer_class`.

| Write | Default status |
| --- | --- |
| create | 201 |
| update | 200 |
| delete | 204 |

A result with nothing to present answers 204 with no body, and a body never
goes out under 204: a value to present answers 200. `success_status` on the
view overrides the default, with an `int` or a callable declaring any of
`result`, `instance`, `request`, `view`; `response_finalizer` may replace the
response built. On a viewset an action may declare its own
([Per-action answers](reference/viewsets.md#per-action-answers)). `as_view()` refuses a callable
requiring a name the view cannot supply, whether or not it also takes
`**kwargs`, which is handed the names the view has and no others.

## Refusals

Every refusal leaves as a DRF exception, so DRF's exception handler, and a
project's `EXCEPTION_HANDLER`, answers it as it answers DRF's own:

| Refusal | Status | Body |
| --- | --- | --- |
| The kernel's `InvalidArguments` (a missing, mistyped or refused argument) | 400 | keyed by argument |
| `ServiceValidationError` | 400 | its error tree |
| A bare `DispatchError` | 400 | `{"detail": ...}` |
| `NotPermitted` (a permission check refusing) | 403 with the check's message. A permission check the spec declares, a kernel `PermissionCheck` or an adapted DRF class, answering `False` to a caller the request's authenticators did not recognise is DRF's `NotAuthenticated` instead, as a DRF view answers it: 401 with the first authenticator's `WWW-Authenticate`, or 403 where it sends none. A service's own `NotPermitted`, an inner `dispatch` its check refused, and a check that raises `NotPermitted` itself rather than answering `False`, stay 403 with their message | `{"detail": ...}` |
| `PrincipalUnavailable` (a deactivated user) | 403 | `{"detail": ...}` |
| `ServiceNotFound`, or a target selector's miss | 404 | `{"detail": ...}` |
| `ActionUnavailable` | 409 | `{"detail": ..., "code": ...}` |
| `ServiceConflict` | 409 | `{"detail": ...}` |
| `AdditionalInputRequired` with a schema | 422 | `{"detail": ..., "schema": ...}` |
| any other `ServiceError` | 422 | `{"detail": ...}` |

The refusal classes the kernel raises through this package's seats are DRF's
as well (`DRFInvalidArguments`, `DRFNotPermitted`, ...), so a caller of the
kernel's `dispatch` catches the kernel's class. See
[DRF seats](reference/service-specs.md#refusals-that-are-drfs-as-well).

## OPTIONS

OPTIONS answers DRF's shape (`name`, `description`, `renders`, `parses`,
`actions`) from the route's specs, and runs no stage of any of them: no
selector, provider, service, precondition or affordance condition.

- **`Allow`** names the methods a spec serves, DRF's `HEAD` beside a `GET`,
  and `OPTIONS`.
- **`actions[POST]` and `actions[PUT]`** are JSON Schema objects of what the
  caller is asked to send, the kernel's `spec_caller_input_schema`: the spec's
  parameters less what the server fills (the keys a seed or a typed provider
  fills), with a key a provider may fill or decline offered and not required,
  none of a `partial` spec's fields required, and a `many` spec's rows read the
  same way by what its `input_data` fills. The route's captures and the target
  lookup's parameters are left out too, since the edge never reads them from
  the body.
- **A method the caller may not send is not described**: DRF's permission
  classes for that method and the kernel's `authorize` for its spec are both
  asked, and either refusing leaves it out of `actions`.

## Serializer context

One context dict is built per request, with `request`, `view`, `format` and
`action`. The input serializer, the output serializer and the service's
`call_context` are handed that same dict, so a key one serializer's
`validate()` writes is there for the service and for the serializer rendering
the answer. See [Serializer context](recipes/serializer-context.md).

## Which transport is calling

That dict also carries the kernel's `"transport"` key, stamped `"rest"`
(`REST_TRANSPORT`, from the package root), so a callable shared with another
transport can tell them apart with the kernel's `call_transport`. Checks, a
discriminator, hooks, the validator, the service, the presenter and an `OPTIONS`
answer all read that one value. The dict is the view's, built by the kernel's
`build_call_context`.

- **A serializer of this package under another transport keeps that transport's
  stamp.** Only a view stamps. A `SerializerValidator` or `SerializerPresenter`
  dispatched by spec-mcp or spec-agents reads their value.
- **A context you write by hand reads as you wrote it.** `build_offline_context`
  returns a request and a view, not a context, so a dict built from them with
  no `"transport"` key reads as an in-process call, where `call_transport`
  answers `None`.
- **The key is the transport's to write.** A view hook or a `serializer_context`
  callable answering a `"transport"` key of its own is dropped from the dict every
  stage shares, silently and without an error, so every stage reads the stamp; name
  such a key something else. A serializer built over a dict of its own (a call with
  no request DRF built) keeps what its layers wrote there, since no other stage reads
  that dict.

What you override on this transport is DRF's and the view's: authenticators and
`EXCEPTION_HANDLER`, the view's attributes and its `get_*` hooks
([Serializer context](recipes/serializer-context.md)).
