# OpenAPI

The opt-in [`drf-spectacular`](https://drf-spectacular.readthedocs.io/)
integration documents each route from its spec.

```bash
pip install "django-spec-rest[spectacular]"
```

```python
from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = "api"

    def ready(self):
        from django_spec_rest.openapi import enable_openapi

        enable_openapi()
```

`enable_openapi()` sets `ServiceAutoSchema` as the schema of `ServiceCreateView`,
`ServiceUpdateView`, `ServiceDeleteView`, `SelectorListView`,
`SelectorRetrieveView`, `ServiceViewSet` and `SelectorViewSet`, and of the
action mixins `ServiceCreateMixin`, `ServiceUpdateMixin`, `ServiceDestroyMixin`,
`SelectorListMixin` and `SelectorRetrieveMixin`, so every subclass inherits it;
a class setting `schema` itself keeps its own. Importing
`django_spec_rest.openapi` does not import `drf-spectacular`; only this call
does.

A viewset of your own over `GenericViewSet`, composed of the action mixins,
inherits the schema only where a mixin comes before `GenericViewSet` in its
bases, as in `class NoteViewSet(ServiceCreateMixin, GenericViewSet)`: DRF's
`APIView` carries a `schema` of its own, so in
`class NoteViewSet(GenericViewSet, ServiceCreateMixin)` that one wins. Where
the mixin does come first, its `ServiceAutoSchema` also wins over a
`DEFAULT_SCHEMA_CLASS` of your own, even a subclass of `ServiceAutoSchema`;
set `schema = YourSchema()` on the viewset to keep the subclass. A
`@service_action` or `@selector_action` on a bare `GenericViewSet` has no mixin
to inherit it from. On drf-spectacular's `AutoSchema` either documents nothing
of its specs. Set `schema = ServiceAutoSchema()` on it (from
`django_spec_rest.openapi.service_auto_schema`), or point DRF's
`DEFAULT_SCHEMA_CLASS` at
`"django_spec_rest.openapi.service_auto_schema.ServiceAutoSchema"`, which
documents a view no spec drives as drf-spectacular does.

## The component names this schema keeps

`ValidationErrors`, `PermissionDenied` and `NotAuthenticated` are the bodies of
a spec's 400, 403 and 401. drf-spectacular keeps the first component it
registers under a name and answers it for every later one, with a warning only,
so a serializer of the project's under one of these names (a
`ValidationErrorsSerializer`, say) would be documented by the refusal's body,
or the refusal by the serializer's fields. Generating the schema refuses it
with `ImproperlyConfigured` instead, on a view of this package's or a view of
the project's on drf-spectacular's own `AutoSchema`, whichever comes first:
the message names the serializer, or the operation (`The operation POST
/notes/`), component or webhook that refers to it. Name the serializer's
component another way with `@extend_schema_serializer(component_name=...)`.

The package's own 403 and 401 bodies are exported, as `PermissionDeniedSerializer`
and `NotAuthenticatedSerializer` from `django_spec_rest.openapi`, for a response
of yours to declare (see [Refusals your project configures](#refusals-your-project-configures)).
Declared on any view, a view of the package's or one on drf-spectacular's own
`AutoSchema`, either is the package's component, in whichever order the views
are resolved. A `$ref` you write yourself to one of these names, such as
`@extend_schema(responses={403: {"$ref": "#/components/schemas/PermissionDenied"}})`,
is refused on any view, a view of the package's included: declare the
serializer instead.

A document in which no spec uses one of these names leaves it to the project:
a `ValidationErrors` component of your own, beside specs that declare no
validator, is documented as yours.

The refusal on a view of the project's is a postprocessing hook,
`django_spec_rest.openapi.reserved_components_hook.reserved_components_hook`,
which `enable_openapi()` inserts first in drf-spectacular's
`POSTPROCESSING_HOOKS`, before your own, once however often it is called. It
runs first because it knows the package's own references by the identity of
their `$ref` strings; a hook of yours that rebuilds them (a JSON round trip)
then sees a document it has already checked. Anything that replaces that
list after `enable_openapi()` runs loses it, such as a `SpectacularAPIView`'s
`custom_settings` setting `POSTPROCESSING_HOOKS`, or a reload of
drf-spectacular's settings: name the hook in that list by its dotted path, or
call `enable_openapi()` again after the reload.

## What a route documents

- **The request body** is a `SerializerValidator`'s serializer, under
  drf-spectacular's component name for the class, built partial where the
  route validates partially: an update route's `PATCH`, or a spec declaring
  `partial`. A `@service_action` `PATCH` runs its spec as declared, so it is
  validated whole and documented whole; a spec declaring `partial` is the way
  to a partial call there, and the same holds for each variant of a decorated
  `DiscriminatedAction`.
  Where the spec's `input_data` fills or may fill one of its fields, the body
  is a component of its own (see below). A `many` spec takes a list of its
  rows. Any other validator is the kernel's
  `spec_caller_input_schema`, less the target lookup's parameters and the
  route's captures, which never come from the body: a key the server fills is
  not offered, and one a provider may fill or decline is offered and not
  required. A `many` spec's rows are read the same way, by what its
  `input_data` fills in every row. `requestBody.required` is stated wherever
  the wire refuses an empty body: every spec the route may run takes a body with
  a required field. A `DiscriminatedAction` with a variant taking no body, or
  none of whose fields is required, leaves it out.
- **A `DiscriminatedAction`'s request** is one component, named
  `{View}_{action}_Request`, whose schema is an `anyOf` over the body of each
  variant that takes one, a body two variants share listed once. It is an `anyOf`
  where drfs' `PolymorphicServiceSpec` documented a `oneOf`, because the edge drops
  a key a variant does not declare: a body one variant takes is also valid for
  another that declares fewer fields. Where no variant takes a body there is no
  request body and no component. Each member is the body its variant would be
  documented with on a plain route of the same method, so a decorated `PATCH`'s
  variants are whole and a variant declaring `partial` is partial. Its responses
  are the variants' merged per status: one body where the variants agree, an inline
  `anyOf` where they differ, and a 400 always, since the discriminator may refuse.
  Two operations whose component name is the same but whose members differ warn
  and document their own `anyOf` inline. See
  [One URL, several specs](reference/viewsets.md#one-url-several-specs).
- **A Validator declaring `call_context`** is asked under the `rest` stamp, as
  dispatch asks it, so a field declared only to `rest` is in the body and a field
  declared only to another transport is not. A document describes the transport
  and never one caller, so `call_context["request"]` is `None` here, and a
  Validator declaring `call_context` guards `request` before reading it. One that
  reads an attribute of that `None` raises `AttributeError` out of generation: a
  document silently missing a body is worse than a failure you see at once.
  OPTIONS is asked under the request it answers, so a field keyed on the caller
  may be offered there and stays out of the document; there, a description that
  raises leaves the method out of `actions`. A `SerializerValidator` reads none
  of this.
- **The response body** is a `SerializerPresenter`'s serializer, or another
  presenter's output schema, a list where the spec presents rows. A spec with
  no presenter documents no content; a selector spec with none keeps the
  view's `serializer_class`, which renders it.
- **The status** is the view's `success_status` where it is an `int`, over the
  action's default. On a viewset it is the action's own where one is declared
  ([Per-action answers](reference/viewsets.md#per-action-answers)). A body documented under 204 is documented as the 200 it is
  served as, with a 204 beside it where the spec can present nothing. A spec that
  can present nothing under a status the view sets answers that status with no
  body, so it lists no 204 beside the body. A spec with
  no presenter answers no content at 204 whatever the action's default, unless
  the view sets a status, so that is what it documents. A `DiscriminatedAction`
  lists each status any of its variants answers.
- **A 400** is documented wherever the spec declares a validator, because that
  is the status a validator's refusal gets, whichever kind refused
  (`SerializerValidator`, `DataclassValidator` or another validator raising the
  kernel's `InvalidArguments`). Its body is the `ValidationErrors` component:
  the errors by name, as DRF sends them, each a list of messages, or an object
  for a nested field, or for a list its rows' errors keyed by the row's index
  (a `many` spec's rows sit under its `many_argument`); the whole call's
  messages are under `non_field_errors`. The 400 is any of three shapes,
  because the edge sends all three: that component; `{"detail": ...}` (the
  `ServiceError` component), for a body that is no object; and a bare list of
  messages, which is what a service's `ServiceValidationError` over a sentence
  or a list answers with. A `ServiceValidationError` over a mapping of
  sentences gives a sentence where the component has a field's list, so a leaf
  of the component is a list of messages or a message. The component's name is
  this schema's: name a serializer's component another way with
  `@extend_schema_serializer(component_name=...)` if it would be named
  `ValidationErrors`, since drf-spectacular keeps one schema for both and
  documents it by the 400's body (or the 400 by its fields). Generating the
  schema refuses such a serializer with `ImproperlyConfigured`, on any view and
  whichever is resolved first (see
  [the names this schema keeps](#the-component-names-this-schema-keeps)).
- **A 422** is documented where the spec declares it can answer one (see
  [Declaring the 422](#declaring-the-422)), whether or not it has a validator.
  It is not a validator's refusal: it is a plain `ServiceError` raised by the
  service, a precondition or a provider. Its body is `{"detail": ...}`, with
  the `schema` an `AdditionalInputRequired` carries beside it when it carries
  one (an object, not required).
- **A selector spec** documents the same two refusals, since a selector is
  refused the same way: a **422** where it declares one (the selector, a
  precondition or a provider can raise a plain `ServiceError`), and a **400**
  where the spec takes any parameter, a read, a shape or a filter. The 400's
  body is the same as a validator's. A route capture is a parameter too: only
  a converter guarantees its type, and a router's default lookup pattern or a
  `str` converter guarantees none. A key the spec declares nothing for is
  dropped rather than refused, so it earns no 400 of its own.
- **A 403** is documented wherever the spec declares a permission check, any
  check but `Unrestricted`: a check's denial and a principal who cannot act (a
  deactivated account) are both answered 403, with the refusal's sentence under
  `detail` (the `PermissionDenied` component). A spec whose checks are all
  `Unrestricted` documents none.
- **A 401** is documented beside it where the view's first authenticator
  sends a `WWW-Authenticate` challenge, such as DRF's `BasicAuthentication` or
  `TokenAuthentication`. Any of those checks denying (answering `False` to) a
  caller nobody authenticated, a kernel `PermissionCheck` or a
  `DRFPermissionCheck` alike, is answered 401 there, under `detail` (the
  `NotAuthenticated` component); behind `SessionAuthentication`, which sends
  no challenge, or a view with no authenticator, the same denial is the 403.
  A check that raises `NotPermitted` itself is answered as raised, 403, with
  no challenge. The 403 and the 401 bodies are the `PermissionDenied` and
  `NotAuthenticated` components, names this schema keeps as it does
  `ValidationErrors`: a serializer of yours that would be the component under
  either (a `PermissionDeniedSerializer` of your own, say) is refused with
  `ImproperlyConfigured`, on any view and whichever is resolved first, until
  you name its component another way with
  `@extend_schema_serializer(component_name=...)`. The package's own
  `PermissionDeniedSerializer` and `NotAuthenticatedSerializer` are the
  components, and yours to declare.
- **A `filter_set`'s query parameters**, on a list operation, are the kernel's
  `filter_set_parameters`.
- **A route capture's type** is drf-spectacular's where it finds one: a
  converter or a regex on the path, or the view's model, which it reads off
  `queryset`. A spec viewset with no `queryset` gives it no model off `list`,
  so there the capture is typed from the read the operation's spec declares
  for it (a retrieve's or a detail action's selector, a write's target
  selector, or the write's own `reads`), with the read's `help` as its
  description. A viewset needs no `queryset` for its schema. A capture no spec
  declares, or that only a validator's field names (the request body's, not
  the route's), stays drf-spectacular's string, with its warning.
- **A viewset method with no spec behind it** is left out where `Allow` leaves
  it out: on a route serving some spec, a `create`, `update`,
  `partial_update` or `destroy` the router maps but the viewset declares no
  spec for answers 405, so it is no operation. A `ServiceViewSet` with no
  `destroy` spec documents no `DELETE`, and one with a `partial_update` spec
  alone documents `PATCH` and no `PUT`. The `list` and `retrieve` handlers,
  which fall back to DRF's queryset, and a handler the viewset defines itself,
  stay documented.

`ServiceErrorSerializer`, a `detail` field and the optional `schema` object, is
the body of that 422 and of the 400's `{"detail": ...}` alternative, under the
`ServiceError` component.

### Declaring the 422

The edge answers any plain `ServiceError` with a 422, but nothing in a spec
says whether its service, selector, preconditions or providers raise one, so
an operation documents the 422 only where its spec declares it, under the
`metadata` key `"document_service_error"` (exported as
`django_spec_rest.openapi.SERVICE_ERROR_METADATA_KEY`):

```python
from django_service_specs import ServiceSpec

from django_spec_rest.openapi import SERVICE_ERROR_METADATA_KEY

book_room_spec = ServiceSpec(
    service=book_room,
    validator=...,
    metadata={SERVICE_ERROR_METADATA_KEY: True},
)
```

It is read off the spec the route serves, on every surface that serves it: a
standalone view's `spec`, an `action_specs` entry, and a `@service_action` or
`@selector_action`. Only that spec's `metadata` is read, never a target or
re-read selector's nested in it. `False`, or no key, documents no 422; any
other value is refused with `ImproperlyConfigured` when the schema is
generated. An `AdditionalInputRequired` is a `ServiceError` too: a spec whose
service asks for more input declares the 422 the same way.

To document it on one view whatever its spec says, declare it there with
`@extend_schema(responses={422: ServiceErrorSerializer})`. To answer for many
operations at once, override `ServiceAutoSchema.documents_service_error(spec)`
in your schema class: it is asked once per operation with the served spec
(`self.view` and `self.method` are the operation's), and returning `True`
documents the 422 on every spec, as releases before 0.7.0 did:

```python
from django_spec_rest.openapi.service_auto_schema import ServiceAutoSchema


class ApiSchema(ServiceAutoSchema):
    def documents_service_error(self, spec):
        return True
```

Your class documents the views it is the schema of: set `schema = ApiSchema()`
on your views, or on a base class they share. `enable_openapi()` sets the
package's own `ServiceAutoSchema` on the package's view classes, which
outranks a `DEFAULT_SCHEMA_CLASS` naming yours, as the top of this page
says.

Every other `@extend_schema` argument a project supplies wins, and
`@extend_schema(parameters=...)` merges over the filter parameters as it does
for a view-level `FilterSet`. `responses=` is added to what the spec documents,
as the next section says.

## Refusals a service raises

Which refusals a service raises is yours to declare: a service may never
raise a `ServiceValidationError`, and a retrieval with a default never answers
404, so the schema documents only what the spec itself shows. Declare the rest
with drf-spectacular's own `@extend_schema(responses=...)`, using the
schema-only serializers `django_spec_rest.openapi` exports. Each documents the
body `map_service_error` sends:

| The service raises | Status | Declare | Body |
| --- | --- | --- | --- |
| `ServiceValidationError` | 400 | `ServiceValidationErrorSerializer` | a list, or an object by name, whose members are a message, a list or an object of the same shape |
| `ServiceNotFound` | 404 | `ServiceNotFoundSerializer` | `{"detail": ...}` |
| `ServiceConflict` | 409 | `ServiceConflictSerializer` | `{"detail": ...}`, and `code` where it is an `ActionUnavailable` |
| `ActionUnavailable` | 409 | `ActionUnavailableSerializer` | `{"detail": ..., "code": ...}` |
| any other `ServiceError` | 422 | the spec's `metadata` (see [Declaring the 422](#declaring-the-422)), or `ServiceErrorSerializer` | `{"detail": ...}`, and `schema` where an `AdditionalInputRequired` carries one |

```python
from drf_spectacular.utils import OpenApiResponse, extend_schema

from django_spec_rest import ServiceUpdateView
from django_spec_rest.openapi import (
    ActionUnavailableSerializer,
    ServiceNotFoundSerializer,
)


@extend_schema(
    responses={
        404: ServiceNotFoundSerializer,
        409: OpenApiResponse(ActionUnavailableSerializer, description="The task is closed."),
    }
)
class CloseTaskView(ServiceUpdateView):
    spec = close_task_spec
```

A mapping of statuses is **added** to what the spec documents: the operation
above still documents its success body, its validator's 400, its permission
check's 403 and any 422 its spec declares, with the 404 and 409 beside them. A status you declare
replaces the spec's at that status (`404` and `"404"` are one status, and so is
a `(404, "application/json")` key), and any `2xx` you declare replaces every
success status the spec documents. Anything else passed as `responses=`, a bare
serializer say, is the success body at the status the route answers with, except
where that is a `204`: the edge sends no body with one, so it stays the
no-content `204`. Only `@extend_schema`'s own subclass is merged this way. A
`ServiceAutoSchema` subclass of yours that overrides `get_response_serializers`
is answered as you wrote it (a status you leave out stays out), and under an
`@extend_schema` it is what the declared statuses are laid over.

A service raising both `ServiceConflict` and its `ActionUnavailable` declares
`ServiceConflictSerializer`, which names `code` without requiring it.
`ServiceValidationErrorSerializer` admits every body the validator's 400
sends, so declaring it on a spec with a validator loses none of them.

The serializers are rendered by `ServiceAutoSchema`'s module, which
`enable_openapi()` loads, so call it first. An `@extend_schema` on a view
**class** builds on the schema the class has when it is decorated: decorated
before `enable_openapi()` runs (a module imported from your `AppConfig`, say),
the class keeps drf-spectacular's own `AutoSchema` and documents nothing of its
spec. Decorating a view method, or an action through `extend_schema_view`, has
no such order, since drf-spectacular reads the class's schema when it
generates the document.

## A serializer body that `input_data` reaches

A field the spec's `input_data` is annotated to fill is never the caller's,
and one it may fill (a key its `TypedDict` declares as `T | UnsetType`) is
not required of the caller, so the body says what OPTIONS says of the same
route. drf-spectacular documents a serializer, so the body is a subclass of
yours with the first kind of field dropped and the second not required,
under a component name of its own. A spec whose `input_data` reaches none of
the serializer's fields keeps your component as it is.

The name is your component's, then `Less` and the fields dropped, then
`Optional` and the fields relaxed. Each list is in sorted order, joined by
`_`, and the two lists, where both are present, by `__`. For a `Task`
component:

| `input_data` fills | it may fill | Component |
| --- | --- | --- |
| `owner` | | `TaskLessOwner` |
| | `owner` | `TaskOptionalOwner` |
| `owner`, `tenant` | `note` | `TaskLessOwner_Tenant__OptionalNote` |
| `owner_id` | | `TaskLessOwnerId` |

A lower `snake_case` field is spelled in `PascalCase`. Any other field name,
such as `ownerId`, is spelled `0` and its UTF-8 bytes in hex, so that no two
sets of fields over one component spell the same name. drf-spectacular adds
what it adds to your own component: `Patched` in front for a `PATCH` or a
`partial` spec (`PatchedTaskLessOwner`), and `Request` behind under
`COMPONENT_SPLIT_REQUEST`. A name set with
`@extend_schema_serializer(component_name=...)` is the stem the subclass is
named from.

An `input_data` provider whose return type does not name its keys (a plain
`dict`) may fill any field, so it requires none: every field is offered and
none is required (`TaskOptionalName_Note_Owner`), as dispatch demands none of
the caller and OPTIONS requires none. The serializer still validates what the
provider leaves out, so a call missing a field the provider did not fill is
still refused. Annotate the provider's return with a `TypedDict` to document
which fields it fills.

## Not documented

A selector spec's declared reads are not documented as query parameters, nor
the affordance envelope a spec declaring affordances renders, nor the `null`
body of an `allow_none` retrieve. Add them with `@extend_schema` where a
client needs them.

A refusal a service raises is not documented unless you declare it (see
above), nor one your project configures (below).

## Refusals your project configures

The 403 and 401 the schema documents are the ones a spec's own checks answer.
Two other sources refuse a caller, and are yours to declare as a service's
refusals are:

- **The view's own `permission_classes` and its authenticators**, which DRF
  asks before the spec: a permission class's denial, and an authenticator
  refusing credentials it cannot verify. Each is a 403, or a 401 with the
  challenge where the view's first authenticator sends one.
- **A principal who cannot act** (a deactivated account), refused 403 on every
  operation, one whose checks are all `Unrestricted` included, which documents
  no 403. Only an authentication backend of your own that signs such a
  principal in can be answered so: DRF's own authenticators and Django's
  `ModelBackend` never do.

Each body is DRF's `{"detail": ...}`, the body of the spec's own 403 and 401.
Declare it with the package's `PermissionDeniedSerializer` and
`NotAuthenticatedSerializer`, which are the `PermissionDenied` and
`NotAuthenticated` components, on a view of the package's or one of your own:

```python
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import IsAdminUser

from django_spec_rest import ServiceCreateView
from django_spec_rest.openapi import NotAuthenticatedSerializer, PermissionDeniedSerializer


@extend_schema(
    responses={
        401: OpenApiResponse(NotAuthenticatedSerializer, description="No credentials were sent."),
        403: OpenApiResponse(PermissionDeniedSerializer, description="The caller is not staff."),
    }
)
class PublishReportView(ServiceCreateView):
    spec = publish_report_spec
    permission_classes = [IsAdminUser]
```

As with a service's refusals, the statuses are added to what the spec
documents, and one the spec documents too is replaced by yours. The bodies
are the spec's own, so a declared 403 still describes the spec's.
