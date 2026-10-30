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
- **A nested selector declares no `permissions`.** On `instance_selector_spec`,
  `collection_selector_spec` and `output_selector_spec` the kernel never asks
  them, so `as_view()` refuses them: declare them on the spec being served.
- **A selector view's `get_selector_kwargs` beside a kernel spec is refused**
  at `as_view()`, with the per-action `get_<action>_selector_kwargs`: return
  those keys from the spec's own `kwargs` provider, which may declare
  `request` and `view`.
- **A viewset's `list` with a spec never goes through `get_queryset()`**; the
  view's filter backends and paginator still apply to the set the spec read.
- **`success_status` and `response_finalizer` are the view's**, read off the
  class for every action, since a kernel spec declares no HTTP answer.

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
- **A `many` spec with an `output_selector_spec` presents what the re-read
  returns**, where drfs presented the service's rows.
- **Bulk and row refusals are worded by the kernel.**
- **OPTIONS runs no stage of a spec** (no selector, provider, service or
  affordance condition) and never answers 500. `Allow` names only the methods
  a spec serves: a handler with no spec is left out, on its 405 too.
  `actions[METHOD]` is a JSON Schema object rather than DRF's per-field
  dictionary, and leaves out the keys the server fills, the route's captures
  and the target lookup's parameters. A mixed viewset's methods that no kernel
  spec serves are no longer described.
- **The browsable API's PUT and PATCH forms are drawn empty**, not prefilled from
  the row: a spec's input need not have the row's fields.
- **OpenAPI** describes a `filter_set`'s parameters by the kernel's
  `filter_set_parameters`: its description wording, a `NumberFilter` as a
  decimal string, an `OrderingFilter` with no `explode` or `style`, in declared
  order, with `maxItems` 1000, a `MultipleChoiceFilter` with `maxItems`, and
  an array as a repeated key. A 422 is documented where the spec has a
  validator. A selector's reads are not documented as query parameters, nor
  the affordance envelope, nor the `null` body of an `allow_none` retrieve.

## Serializer context

- **One context dict per request.** The input serializer, the output serializer
  and the service's `call_context` are handed the same dict, so a key one
  serializer's `validate()` writes is there for the service and the output
  serializer, as in a stock `ModelViewSet`. drfs handed each serializer a copy.
- **A presenter's `serializer_context` callable runs once per row** of a list,
  not once for the page, so a callable that queries runs that query per row.
- **A kernel selector gets no `get_<action>_output_serializer_context`** hook:
  declare the context on its `SerializerPresenter`.

## Permissions

- **`DRFPermissionCheck` takes `route_reads=`** for the arguments that go onto
  the offline view's `kwargs`; its `url_kwargs=` and `query_params=` are gone,
  and the offline request's query string is empty.
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
- `@service_action` does not run the kernel's seed check at `as_view()`.
- `ActionSerializerResolver` falls back to the view's `serializer_class` for an
  action whose spec has no serializer.
- A service's `ServiceValidationError` keyed by a model field is answered under
  that name, not renamed to the serializer field whose `source` it is.

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
