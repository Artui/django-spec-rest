# Moving from djangorestframework-services

`django-spec-rest` is `djangorestframework-services` (drfs) moved onto the
kernel, [`django-service-specs`](https://artui.github.io/django-service-specs/).
Its views, viewsets and decorators keep their names; what they serve is now
the kernel's own `ServiceSpec` and `SelectorSpec`, and DRF enters a spec
through three seats: a `SerializerValidator`, a `SerializerPresenter` and a
`DRFPermissionCheck`. drfs' own declaration types are gone, and with them
every name that re-exported a kernel object.

This page lists what a project moving from drfs 0.62.0 rewrites, and what its
clients see change. drfs' history is in its
[archived changelog](https://github.com/Artui/djangorestframework-services/blob/main/CHANGELOG.md).

## Installing

| drfs | django-spec-rest |
| --- | --- |
| `pip install djangorestframework-services` | `pip install django-spec-rest` |
| `import rest_framework_services` | `import django_spec_rest` |
| `"rest_framework_services"` in `INSTALLED_APPS` | nothing: the package has no models, templates or app config, so remove the entry |
| the `startserviceapp` management command | none |
| `djangorestframework-services[spectacular]` | `django-spec-rest[spectacular]` |

The package reads no setting of its own. `SPEC_REST` is reserved as the name
of the first one.

## The codemod

The repository carries a codemod,
[`tools/drfs_codemod`](https://github.com/Artui/django-spec-rest/blob/main/tools/drfs_codemod/README.md),
that does the mechanical part of this page in place. It is not in the wheel:
run it from a clone, with `libcst` installed, over the project's own modules.

It rewrites each drfs import by the module it names, following the
[import map](#the-import-map), so a kernel name spelled like a drfs one is never
taken for it. It turns each drfs `ServiceSpec` and `SelectorSpec` into the
kernel's, moving each field onto its seat as [below](#declaring-a-spec): the
serializers and their contexts, `permission_classes`, an output selector's
serializer and context, `document_service_error` and `field_audiences`. A
spec's `success_status` and `response_finalizer` move to the views in the same
module that serve it, as [Views and viewsets](#views-and-viewsets) places them.
A second run changes nothing.

Every site it leaves gets a comment beginning `# drfs-codemod:` above its
statement, giving the reason, and a line of its report, `path:line: reason`.
A site stays in the report until its comment is deleted. `--check` writes
nothing and exits 1 while a file would still change.

What it does not do:

- **Declare reads.** drfs handed a selector the route captures and query
  values its signature named; the kernel hands it only the `reads=` its spec
  declares. The codemod reads the selector's `def` and writes the
  `reads=Parameters.of(...)` it would take into the marker, but applies none,
  since a key a provider or the server filled would become the caller's to
  send.
- **Translate a `UrlKwarg` or `QueryParam` list.** A drfs `reads=` is marked
  and kept as it was, for a `Parameter` declaring its type to replace it.
- **Split a `PolymorphicServiceSpec`** into one kernel spec per route or
  action, nor replace `OfflineContract`, `TargetGuard`, `ArgumentBinding` or
  an input marker (`InputRequired`, `NotClientInput`, `InputDescription`). A
  use of one is marked, and its import kept.
- **Answer from another module.** A `success_status` or `response_finalizer`
  whose view is in another module, or that no view serves, is marked on the
  spec: set it on that view.
- **Follow a module import of drfs.** `import rest_framework_services` (or a
  submodule) is marked, and a spec built through it, such as
  `drfs.ServiceSpec(...)`, is left whole.
- **Format.** What it writes keeps the layout of what it replaced, and a
  keyword it adds may make a line long; run the project's formatter after
  it.

## The import map

The package root exports [29 names](reference/index.md#public-surface), none of
them the kernel's. A name drfs re-exported from the kernel is imported from
`django_service_specs`.

| drfs spelling | Becomes |
| --- | --- |
| `rest_framework_services.<path>` for a view, viewset, mixin, decorator or type this package keeps | `django_spec_rest.<path>` |
| `ServiceSpec`, `SelectorSpec`, `SelectorKind` | `django_service_specs`: the kernel's own, declared as [below](#declaring-a-spec) |
| any other kernel name drfs re-exported (`ServiceError` and its subclasses, `Affordance`, `UNSET`, `ChangeResult`, the relation declarations, `PoolSeeds`, `FieldMarking`, `FieldAudience`, `SpecRegistry`, `create_from_input`, `update_from_input`, `apply_input`, ...) | `django_service_specs`, from its root |
| `can_present_nothing`, `server_owned_keys`, `unguarded_specs`, `resolve_callable_kwargs`, `audience_projection_for_spec`, `enforce_affordances`, `unmet_operation_affordance` and their `a`-prefixed async twins | the kernel's functions of the same names, from `django_service_specs` |
| `dispatch_spec`, `adispatch_spec` | the kernel's `dispatch`, `adispatch` |
| `render_spec_output`, `render_for_audience` and their async twins | the kernel's `present`, `present_for_audience` |
| `enforce_permissions` | the kernel's `authorize` |
| `call_service`, `call_selector`, `apply_queryset_shaping` and their async twins | the kernel's `run_service`, `run_selector`, `shape_queryset` |
| `spec_to_json_schema`, `output_to_json_schema`, `serializer_to_json_schema` | the kernel's `spec_input_schema` and `spec_output_schema` |
| `filterset_to_json_schema` | the kernel's `filter_set_parameters` |
| `InvalidArguments`, `NotPermitted`, `PrincipalUnavailable` from `service_specs` | `DRFInvalidArguments`, `DRFNotPermitted`, `DRFPrincipalUnavailable`, each still the kernel's class and DRF's ([DRF seats](reference/service-specs.md#refusals-that-are-drfs-as-well)) |
| `SerializerValidator`, `SerializerPresenter`, `DRFPermissionCheck` | the same names, under `django_spec_rest.service_specs.<module>` |
| `capability_manifest`, `build_audience_projection`, `build_input_serializer`, `validate_input` | none: each read a drfs spec |

## Declaring a spec

drfs' `ServiceSpec`, `SelectorSpec`, `PolymorphicServiceSpec`, `UrlKwarg`,
`QueryParam`, `ArgumentBinding`, `OfflineContract`, `TargetGuard` and the input
markers (`InputRequired`, `NotClientInput`, `InputDescription`) are gone. A
spec is the kernel's, and each drfs field maps onto one of its seats:

| drfs field | Kernel spec |
| --- | --- |
| `input_serializer=S` | `validator=SerializerValidator(S)` |
| `input_serializer_context=` | `SerializerValidator(S, serializer_context=...)` |
| `output_serializer=S` | `presenter=SerializerPresenter(S)` |
| `output_serializer_context=` | `SerializerPresenter(S, serializer_context=...)` |
| `permission_classes=[...]` | `permissions=(DRFPermissionCheck([...]),)`; a spec that admits everyone says so with the kernel's `Unrestricted()` |
| `reads=[UrlKwarg("pk")]`, `reads=[QueryParam("status")]` | `reads=Parameters.of(Parameter("pk", "integer", required=True))`: the edge reads a declared read from the route first, then the query string |
| a `QueryParam` no callable names | `shapes=Parameters.of(...)` |
| `NotClientInput`, a hidden lookup key | a typed `kwargs` provider filling the key, which the kernel then keeps out of the caller's arguments (`server_owned_keys`) |
| `PolymorphicServiceSpec` | one kernel spec per route or action; the polymorphic request body and its `{View}_{action}_Request` OpenAPI component are gone |
| `TargetGuard` | the kernel's preconditions and object permission, which see the row |

`JsonSchemaRegistry` keeps its `fields` rules alone. Its `filters` and
`python_types` rules are gone: a `filter_set` is described by the kernel's
`filter_set_parameters`, and each read is a `Parameter` declaring its own type,
so a project passing either to `extend()` or the constructor drops it.

The example project's [views](https://github.com/Artui/django-spec-rest/blob/main/examples/invoices/views/__init__.py)
declare every seat above.

## Views and viewsets

- **`spec` and `action_specs` take kernel specs.** `@service_action(spec)` and
  `@selector_action(spec)` take them too. A kernel spec under an
  `action_specs` key no action dispatches is refused at `as_view()`, since its
  permissions would guard nothing: serve it with a decorator.
- **A write's target is its spec's own selector, never `get_object()`.** An
  update or delete spec declares `instance_selector_spec` (one row) or
  `collection_selector_spec` (a set) or `many=True`, and `as_view()` refuses one
  that declares none. A `get_object()` override no longer chooses a write's
  row.
- **A route capture is read only where a spec declares it.** drfs handed a
  selector the captures its signature took (`InputRequired`,
  `Unpack[...UrlExtras]`); the kernel hands a spec only its declared
  parameters. On a router-mounted detail route, `as_view()` refuses an action
  whose row lookup (the `retrieve` spec, a detail `@selector_action`'s, or a write's
  `instance_selector_spec`) declares no parameter named for the lookup capture
  (`lookup_url_kwarg`, else `lookup_field`): add
  `reads=Parameters.of(Parameter("<capture>", ..., required=True))` to that
  selector. A viewset mounted by hand and a standalone view are not checked,
  since their captures are the URLconf's: declare each capture the route
  carries yourself
  ([The lookup capture](reference/viewsets.md#the-lookup-capture)).
- **A nested selector declares no `permissions`.** On `instance_selector_spec`,
  `collection_selector_spec` and `output_selector_spec` the kernel never asks
  them, so the kernel refuses them when the `ServiceSpec` is built: declare
  them on the spec being served.
- **A selector view's `get_selector_kwargs` beside a kernel spec is refused**
  at `as_view()`, with the per-action `get_<action>_selector_kwargs`: return
  those keys from the spec's own `kwargs` provider, which may declare
  `request` and `view`.
- **A viewset's `list` with a spec never goes through `get_queryset()`**; the
  view's filter backends and paginator still apply to the set the spec read.
- **`success_status` and `response_finalizer` are the view's or the action's**,
  since a kernel spec declares no HTTP answer. A drfs spec's value moves to the
  route that served it: on a standalone view or a viewset whose actions all
  answer alike, the class attribute; on a `@service_action`, the decorator's
  `success_status=` and `response_finalizer=`; on an `action_specs` entry, a
  `get_<action>_success_status` or `get_<action>_response_finalizer` hook,
  a method declaring what the callable did, or an `int` for a status
  ([Per-action answers](reference/viewsets.md#per-action-answers)).

## What a client sees

### The query string

The query string is read by the kernel's flat reader:

- **A blank filter or a blank declared read is absent.** `?status=` answers what
  no parameter answers, where drfs answered 400.
- **A multiple-choice filter splits on a comma and takes a blank**:
  `?st=ann,bob` and `?st=` answer 200.
- **A typed array splits on a comma**: `ids=1,2` is `[1, 2]`, and `ids=1,,3`
  answers 400 at the empty element.
- **An array is read no further than one past its cap**, and refused with the
  same 400.
- **A key no parameter declares is dropped**, `csrfmiddlewaretoken` among them.
  A selector parameter declared only in its signature receives nothing from
  the query string: declare it in `reads`.

### Bodies and arguments

- **A form body is read as DRF reads one** (`"on"`, a blank checkbox, the
  prefixed spellings `v.tenant` and `tags[0]` of a nested or list field), and a
  JSON body is checked against the spec's declared types as sent: `"true"` is
  no boolean in JSON.
- **A JSON integer field still takes a numeric string.** `{"start_hour": "10"}`
  is accepted as `10`, as drfs accepted it, while `{"title": 5}` is refused
  with `Expected a string.`: "as sent" is a check of the kind of value, and the
  kernel reads a numeric string as a number but not a number as a string.
- **A JSON field's refusal is worded by the kernel, not DRF.** `Date has wrong
  format. Use one of these formats instead: YYYY-MM-DD.` is `Enter a valid
  date.`, `A valid integer is required.` is `Expected an integer.`, and `This
  field may not be null.` is `This field cannot be null.`. A client matching
  on a message must match the new one; the keys and the 400 are unchanged.
  A form body keeps DRF's wording, since the serializer answers it.
- **A body that is no object answers `{"detail": "The body must be an object;
  got list."}`**, where drfs answered `{"non_field_errors": ["Invalid data.
  Expected a dictionary, but got list."]}`. Both are a 400.
- **A body key named `request`, `view` or `serializer` that no field declares
  is dropped**, as any undeclared key is; it never reaches the seed of that
  name.
- **A target selector's filter and its reads come from the route and the query
  string, never the body.** On an update or delete a body value cannot choose
  the row or set the lookup's `filter_set` scope.
- **A `kwargs` provider key naming a validator field is refused**, pointing at
  `input_data=`: a typed provider's when the view is built, an untyped one's on
  the request whose answer names one. A key named like a field's `source`
  stays the provider's.
- **A view hook's value outranks the validated value**: a key
  `get_service_kwargs` returns that the serializer also declares writable
  reaches the service as the hook's value, so a client cannot overwrite a
  hook setting `owner=request.user`.
- **A provider value named like a filter reaches the filter**, over the query
  string's: the kernel has one argument namespace.
- **The route's format suffix wins for `format`** over a
  `get_serializer_context()` override returning its own.

### Answers

- **A bare `DispatchError` answers 400** with its sentence under `detail`, where
  drfs answered 500.
- **An output serializer refusing to render answers 400 as a mapping.** A
  `ValidationError` raised from `to_representation` with a list (a message, as
  DRF makes of a string) is keyed under `non_field_errors`:
  `{"non_field_errors": ["..."]}`, where drfs answered the bare list. A mapping
  is kept as it is. A page of rows renders as one `many=True` serializer, so a
  list refusal there answers the same.
- **A `many` spec with an `output_selector_spec` presents what the re-read
  returns**, where drfs presented the service's rows.
- **Bulk and row refusals are worded by the kernel.**
- **OPTIONS runs no stage of a spec** (no selector, provider, service or
  affordance condition) and never answers 500. `Allow` names only the methods
  a spec serves: a handler with no spec is left out, on its 405 too.
  `actions[METHOD]` is a JSON Schema object rather than DRF's per-field
  dictionary, and leaves out the keys the server fills, the route's captures
  and the target lookup's parameters; a key a provider may fill is described
  and not required. A mixed viewset's methods that no kernel
  spec serves are no longer described.
- **The browsable API's PUT and PATCH forms are drawn empty**, not prefilled from
  the row: a spec's input need not have the row's fields.
- **OpenAPI** describes a `filter_set`'s parameters by the kernel's
  `filter_set_parameters`: its description wording, a `NumberFilter` as a
  decimal string, an `OrderingFilter` with no `explode` or `style`, in declared
  order, with `maxItems` 1000, a `MultipleChoiceFilter` with `maxItems`, and
  an array as a repeated key. A validator's refusal is documented as the 400 it
  answers. A selector's reads are not documented as query parameters, nor
  the affordance envelope, nor the `null` body of an `allow_none` retrieve.
- **The 422 is documented only where a spec declares it.** drfs documented the
  422 of a plain `ServiceError` on every spec with an `input_serializer`,
  unless `document_service_error=False`; spec-rest documents it on no spec, a
  service's or a selector's, unless the spec's `metadata` says
  `{"document_service_error": True}` (`SERVICE_ERROR_METADATA_KEY` in
  `django_spec_rest.openapi`). So a drfs `document_service_error=True` moves
  into `metadata`, `False` and `None` are dropped, and a schema generated
  from the same views loses its 422s until the specs that raise one declare
  it. A schema subclass that popped the 422 through drfs' private
  `resolve_service_spec` has nothing left to pop; one that wants the 422
  everywhere overrides `ServiceAutoSchema.documents_service_error` to return
  `True` ([Declaring the 422](openapi.md#declaring-the-422)).

## Serializer context

- **One context dict per request.** The input serializer, the output serializer
  and the service's `call_context` are handed the same dict, so a key one
  serializer's `validate()` writes is there for the service and the output
  serializer, as in a stock `ModelViewSet`. drfs handed each serializer a copy.
- **A presenter's `serializer_context` callable receives what drfs' provider
  did**: a list's rows under `page`, once for the page, and one value under
  the presenter's `value_keyword` (`result` by default; set
  `value_keyword="instance"` for a retrieve provider declaring `instance`). A
  `many` service's provider declaring `result` receives its whole return.
  `page` is always a list of the rows, never a queryset: as drfs did on a
  paginated view, and unlike drfs on an unpaginated one, where it handed the
  selector's queryset. A provider calling a queryset method on it
  (`page.values_list(...)`, `page.filter(...)`) must change to work over the
  list, for example `[row.pk for row in page]`
  ([Serializer context](recipes/serializer-context.md#what-a-presenters-callable-receives)).
- **A kernel selector gets no `get_<action>_output_serializer_context`** hook:
  declare the context on its `SerializerPresenter`.

## Permissions

- **`DRFPermissionCheck` takes `route_reads=`** for the arguments that go onto
  the offline view's `kwargs`; its `url_kwargs=` and `query_params=` are gone,
  and the offline request's query string is empty.
- **An adapted DRF class still asks a caller nobody authenticated to sign in.**
  A DRF class in `DRFPermissionCheck` denying a caller the request's
  authenticators did not recognise is answered DRF's `NotAuthenticated`, as
  drfs' view answered it: 401 with the first authenticator's
  `WWW-Authenticate` (`Basic realm="api"` with `BasicAuthentication` first),
  or 403 "Authentication credentials were not provided." where that
  authenticator sends no challenge, as `SessionAuthentication` does not. A
  signed-in caller, and any caller of a view with no authenticator, is refused
  403 with the class's own `message`. Off HTTP there is no authenticator, so
  the refusal is the kernel's `NotPermitted`.
- **A kernel `PermissionCheck` asks a caller nobody authenticated to sign in**
  too: 401 with the challenge, or 403 where the first authenticator sends
  none, and 403 with its message to anyone else. A service's own
  `NotPermitted`, and an inner dispatch its check refused, stay 403 with their
  message for every caller.
- **A refusal comes before the body is read**, as drfs' view asked its
  permission classes in `initial()`. The spec's checks are asked before its
  arguments' shape is checked, so a caller they refuse gets the 401 or 403
  above whatever it sends: an empty body, a missing field, a value of the
  wrong type or a query string the read cannot parse answer the same as a
  well-formed request, never the 400 that lists the fields. A request whose
  body or query string fails its shape is judged with no arguments, the
  question the OPTIONS answer asks before it describes a method, so OPTIONS
  shows a method's schema exactly to the callers whose incomplete request is
  told what it lacks. A check that reads the call's arguments and cannot
  answer without them keeps the kernel's order: the caller is told the 400
  first, and the check is asked once the shape passes. A check that answers
  `False` with no arguments refuses every caller sending an incomplete body.
- **`DRFPermissionCheck` can raise `DRFNotAuthenticated`**, not only
  `DRFNotPermitted`, when the call carries a real DRF request with
  authenticators and nobody was recognised. `DRFNotAuthenticated` is DRF's
  `NotAuthenticated`, not a `PermissionDenied`, so code catching
  `PermissionDenied` by name around such a dispatch no longer catches that
  refusal; catch the kernel's `NotPermitted`, which both classes are.
- **`UNAUTHENTICATED_USER = None` is passed as `None`**: the principal an
  anonymous request hands the kernel is `None` where the project sets it so,
  rather than an `AnonymousUser`.

## Answers kept as they are

- **The target lookup runs before the shape check** refuses a body key, so a
  lookup's selector and provider are called for a body the check then refuses.
- **A provider's `"abc"` or `None` reaches an `x: int` selector parameter** as
  returned: a provider is server code, and its values are not coerced.
- **A serializer that cannot be described when the view is built** (its
  `get_fields` reads `context["request"]`, or a key only the view adds) skips
  the kernel's seed check at `as_view()`; its first request is checked instead.

## Known limits

- A kernel spec under `@selector_action` does not read the view's
  `get_selector_kwargs`, and nothing refuses the override there.
- A `@service_action` or `@selector_action` spec is seed-checked by its
  viewset's `as_view()`, so only on a viewset built on this package's bases.
  On DRF's own `GenericViewSet` or `ViewSet` nothing runs the kernel's seed
  check, and a keyword nothing fills is the action's first request's
  `TypeError`.
- `ActionSerializerResolver` falls back to the view's `serializer_class` for an
  action whose spec has no serializer.
- A service's `ServiceValidationError` keyed by a model field is answered under
  that name, not renamed to the serializer field whose `source` it is.
- A kernel `dispatch` a service makes of the view's own spec for another
  principal validates under that principal's own context, but its declared
  parameter set is still the one described under the view's request, until
  the kernel passes the asking call to `parameters()`.
- The input serializer is first built with no body and no row, to describe its
  fields, so one reading `self.initial_data` or `self.instance.<attr>` in
  `__init__` or `get_fields` raises `AttributeError` on every request, a 500,
  while `as_view()` accepts it. Guard the read, as
  `getattr(self, "initial_data", {})` or `if self.instance is not None:`:
  the serializer that validates is bound to the body and the row, so a field
  the guarded read adds there is required and validated.
- A `many` spec's row field named like a dispatcher seed, such as `user` or
  `result`, is dropped from each row: refused as missing where it is required,
  and validated without the value the client sent where it is optional. Name
  the field otherwise and give it `source="user"` where the row must still
  carry that key.
- The input serializer is built several times per call, to describe its
  fields as well as to validate, so the queries its `__init__` or
  `get_fields` makes run several times. Where their count matters, move them
  to the service, or to `validate()` or a `validate_<field>()`, which only the
  validating build runs.
- A row condition among a create spec's `affordances` is refused only when the
  view dispatches, with `ImproperlyConfigured` on the first request, not at
  `as_view()`. Declare row conditions only on a spec with an
  `instance_selector_spec`.

## Authenticating MCP calls through DRF

[`django-spec-mcp`](https://github.com/Artui/django-spec-mcp) serves the same
kernel specs to agents. Neither package ships a bridge between DRF's
authentication and the MCP transport; a project that wants its DRF
authentication classes to admit MCP calls writes a backend of its own. The
transport calls `authenticate(request)` with the Django request and expects a
`TokenInfo`, or `None` for a 401:

```python
from django.http import HttpRequest
from django_spec_mcp import TokenInfo
from django_spec_mcp.auth import bearer_challenge
from django_spec_mcp.auth.types.protected_resource_metadata import ProtectedResourceMetadata
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import APIException
from rest_framework.request import Request


class DRFAuthBackend:
    """Admits an MCP call that the project's DRF authentication classes admit."""

    authentication_classes = (TokenAuthentication,)
    resource_url = "https://example.com/mcp/"

    def authenticate(self, request: HttpRequest) -> TokenInfo | None:
        drf_request = Request(
            request, authenticators=[cls() for cls in self.authentication_classes]
        )
        try:
            user = drf_request.user
        except APIException:
            # An invalid credential: DRF raises AuthenticationFailed.
            return None
        if drf_request.successful_authenticator is None:
            return None
        return TokenInfo(user=user, raw=drf_request.auth)

    def protected_resource_metadata(self) -> ProtectedResourceMetadata:
        return ProtectedResourceMetadata(resource=self.resource_url, authorization_servers=[])

    def www_authenticate_challenge(self, *, scopes=None, error=None) -> str:
        return bearer_challenge(
            resource_metadata_url=f"{self.resource_url}.well-known/oauth-protected-resource",
            scopes=scopes,
            error=error,
        )
```

Prefer a header-borne credential class (`TokenAuthentication`, a JWT class):
`SessionAuthentication` enforces CSRF on the transport's `POST`. Scopes are the
transport's to check, with its own `scopes=`.
