# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This package continues `djangorestframework-services`, whose history it
carries; releases up to 0.62.0 are in
[that package's changelog](https://github.com/Artui/djangorestframework-services/blob/main/CHANGELOG.md).

## [Unreleased]

### Fixed

- **A nullable or labelled schema no longer makes an OpenAPI 3.0 document
  invalid.** The kernel writes JSON Schema: a nullable field's type is
  `[t, "null"]`, a labelled parameter choice an `anyOf` of `{"const", "title"}`,
  and a labelled output choice a `oneOf` of the same. 3.0, drf-spectacular's
  default `OAS_VERSION`, has neither a type list nor `const`, so
  `validate_schema` refused the whole document. Under 3.0 such a schema is now
  written as `nullable` and `enum` wherever the kernel's schema enters the
  document: a request body, a response body, a route capture a spec reads and a
  `filter_set`'s query parameter, nested under `properties` and `items` as
  deep as they go. A choice and a null are one `enum` listing `null` beside
  `nullable: true`. The titles are dropped, since 3.0 has no place for them.
  Under 3.1 and later the schema is kept as the kernel writes it. What OPTIONS
  answers is unchanged.

## [0.11.0] — 2026-11-09

### Added

- **OPTIONS and the OpenAPI body read a spec under the `rest` stamp.** Each asks
  `spec_caller_input_schema` with a `call_context`, so a field a Validator
  declares only to `rest` is offered by both and required where dispatch requires
  it, and one declared only to another transport is offered by neither. OPTIONS
  hands the call's own dict; a document describes the transport and never one
  caller, so OpenAPI hands `build_call_context("rest", view=view)`, with
  `request` `None`. A Validator declaring `call_context` guards `request`: a
  description that raises `AttributeError`, `KeyError` or `TypeError` is left out
  of OPTIONS, as before, and any other exception is a 500. A
  `SerializerValidator`'s output does not move. Requires
  `django-service-specs>=0.30.0`.
- **Both seats name the action the wire names.** A Validator keyed on
  `call_context["action"]` saw `None` in the document, `"metadata"` in OPTIONS and
  the action's name in dispatch, so a field it requires only for that action was
  missing from both descriptions and the wire answered `400` for it. The document
  now hands the view's action, and OPTIONS a copy of the call's dict naming the
  action each described method dispatches as (the route's `action_map` entry, none on a
  standalone view); the view's own dict is untouched.
- **The docs and the example say what `DiscriminatedAction` does.** The viewsets
  reference has a section on it (where it attaches, who is refused before the body
  is read, the row, validation per variant, `variant` for a status or finalizer),
  the OpenAPI page names its `{View}_{action}_Request` `anyOf` component and its
  merged responses, and `examples/invoices` serves one as `POST /intake/`, asserted
  over HTTP and in the schema by `make examples`. The moving page's off-HTTP
  default now names the HTTP transports (`"rest"`, `"html"`) and says what it means
  for each of `"agent"`, `"mcp"`, `"cli"` and an unstamped call, where it compared
  `("agent", "mcp")` and left out spec-cli's value.

### Changed

- **A Validator declaring `call_context` that guards only `call_context is None`
  now raises out of OpenAPI generation.** Generation handed it no dict before; it
  now hands one with `request` `None`, so a Validator that guards `call_context is
  None` and then reads `call_context["request"].user` generated and now fails with
  an `AttributeError`. Guard `call_context["request"] is None` instead. A
  document silently missing a body is worse than a failure its author sees at once.
- **`django_spec_rest.W001` also reports a retrieve-only viewset.** A retrieve
  ignores `get_queryset()` as a write or a list does, so tenant scoping left in an
  override let a `GET` read another tenant's row with no error, and the guard said
  nothing. `as_view()` now reports an override beside any spec, whatever its kind,
  and `spec_rows_scoped_by_selector = True` silences it as it does the others. A
  viewset that overrides `get_queryset()` and serves only `retrieve` specs, which
  built silent before, now warns once at `as_view()`; set the attribute once each
  selector scopes its own rows. The warning's text now reads "serves a spec", and
  the reference page says that a router-mounted viewset's `file:line` is DRF's
  `rest_framework/routers.py`, since the router calls `as_view()`; the text names
  the class.

### Fixed

- **A viewset read with nothing to fall back to answers 405, not DRF's assertion
  as a 500.** A `list` or `retrieve` with no spec on a viewset with no rows
  (`queryset`, `get_queryset()`) or no serializer (`serializer_class`,
  `get_serializer_class()`, `get_serializer()`) raises `MethodNotAllowed` as an
  unserved write does, and `Allow`, OPTIONS and the schema follow from one
  predicate. So a create-only `ServiceViewSet` on a router answers 405 on `GET`
  and `HEAD`, documents `POST` alone, and keeps a detail route, which a router
  mounts, with `Allow: OPTIONS` and no schema path. A project's own `list`,
  `retrieve`, `get_object()`, `get_queryset()`, `get_serializer_class()` or
  `get_serializer()` still answers, each for the half it supplies, and the rule
  that a `list` or `retrieve` fallback stays documented narrows to one that can
  run. OPTIONS of a project's own write on such a viewset answers with that method
  undescribed, where DRF's metadata asserted.
- **`@selector_action` refuses a spec that is not a `SelectorSpec` where it is
  decorated.** A `ServiceSpec`, a `DiscriminatedAction` or anything else failed
  as an `AttributeError` at `spec.kind`, saying nothing of what to do. It is now
  an `ImproperlyConfigured` naming the action and the way out: a write goes to
  `@service_action`, anything else wants the `SelectorSpec` the action reads through.
- **A caller a plain spec refuses is refused whatever it sends, a body that cannot
  be read included.** An unparseable body answered DRF's 400, an unsupported media
  type its 415 and too many form fields Django's 400, with no challenge, ahead of
  the spec's checks. The edge now judges a failed read on no arguments, as it
  judges a failed shape and as a `DiscriminatedAction` route already did, so an
  anonymous caller gets the 401 with the challenge, or a 403 where the first
  authenticator gives none, and a signed-in one the check's 403. A caller the
  checks admit is told what the read raised, as before, and OPTIONS hides a
  method from the same callers. A view hook that reads the body first is judged
  the same; hooks still run before the checks, and the body is not read ahead of
  them.
  A hook raising one of those errors itself is judged the same way, which it cannot
  be told from. A refused caller's too many form fields no longer writes to Django's
  `django.security.TooManyFieldsSent` log, so a project alerting on it stops hearing
  from callers it refuses; an admitted caller's still does.
- **A `@service_action` `PATCH` is documented as the wire validates it.** The
  action runs its spec as declared, so its body is validated whole, and the
  document no longer calls it partial: its `required` list is the one the wire
  demands, on each variant of a decorated `DiscriminatedAction` too. Nothing on
  the wire changes. A spec declaring `partial` is the way to a partial call.
- **A spec with no presenter is documented at both statuses it may answer.** The
  edge answers `204` for one where the service returns `None` (unless the view sets
  a status) and the action's default with the value where it returns anything
  else, and `allow_none` is a declaration no document can read, so the document
  lists both with no schema: `201` and `204` on a create, `200` and `204` on a
  custom action. It named the default alone, which was wrong for a service
  returning nothing. A destroy lists `204` alone, its default, and a status the
  view sets is the one status; a bare `@extend_schema(responses=Foo)` lands on the
  default. A `DiscriminatedAction` with one variant presenting and one not now
  lists both statuses, where the second's `204` went undocumented. A spec that may present
  nothing under a status the view sets no longer lists a `204` it never answers:
  the bodyless answer goes out at that status.
- **`requestBody.required` where the body is a schema given whole.** drf-spectacular
  reads such a body as optional, so a `DiscriminatedAction`, and a plain spec over
  any Validator but a `SerializerValidator`, stated nothing while the wire answered
  `400` for an empty body. It is stated wherever every spec the route may run takes
  a body with a required field, and stays absent where one takes no body or
  requires none of its fields.
- **A project's own `transport` key no longer replaces the stamp.** A view hook or a
  `serializer_context` callable answering a `"transport"` key wrote it into the
  call's one dict, so every later stage read the project's value in place of
  `"rest"`, against the kernel's contract that the transport stamps last. The key is
  now dropped from that shared dict, as `format` already was, without an error. A
  serializer built over a dict of its own keeps what its layers wrote.

## [0.10.0] — 2026-11-08

### Added

- **A view stamps its call's context `"rest"`.** The request's one dict is built
  through the kernel's `build_call_context` and carries `call_context["transport"]
  == "rest"`, so checks, a discriminator, hooks, the validator, the service, the
  presenter and an `OPTIONS` answer read one value through the kernel's
  `call_transport`. The value is `REST_TRANSPORT`, from the package root. A
  serializer of this package running under another transport's `dispatch` leaves
  that transport's stamp alone, and a context written by hand from
  `build_offline_context` reads as its caller wrote it. Requires
  `django-service-specs>=0.29.0`.
- **A `get_queryset()` override beside a spec is reported.** A spec's rows are
  its selector's, so tenant scoping left in a viewset's `get_queryset()` narrows
  nothing, and a `PATCH` or `DELETE` reaches another tenant's row with no error.
  `as_view()` now warns of a viewset overriding it while serving a write spec
  or a list spec: a `GetQuerysetScopeWarning`, from `django_spec_rest`, whose
  text begins with the stable id
  `django_spec_rest.W001` and names the class. Set
  `spec_rows_scoped_by_selector = True` on a class to silence it once its
  selectors scope their own rows; it is inherited, and covers only overrides on
  that class and its bases. A project needs no `INSTALLED_APPS` entry to get
  it, so it is a Python warning rather than a system check, and
  `SILENCED_SYSTEM_CHECKS` does not apply. `filter_backends` are not reported,
  and the [moving page](https://artui.github.io/django-spec-rest/moving-from-drfs/#views-and-viewsets) now says a
  tenant backend loses its scoping the same way.

- **`DiscriminatedAction`: one action at one URL, chosen by the request.** drfs'
  `PolymorphicServiceSpec` returns as an opt-in for an endpoint that must keep
  one URL; one kernel spec per route stays the default. `DiscriminatedAction(
  discriminator=, specs=)` maps each key the discriminator may answer to a
  kernel `ServiceSpec`, and attaches as an `action_specs` entry under `create`,
  `update`, `partial_update` or `destroy`, or as `@service_action(...)`, which
  now accepts it. It is this package's alone, not a kernel spec: agents and MCP
  register each variant on its own. A caller every variant refuses is refused
  before the body is read; otherwise the chosen variant runs as a plain entry
  would, its own checks deciding, so drfs' `permission_strategy=` is gone. A
  callable `success_status` or `response_finalizer` on such an action may
  declare `variant`, the chosen key. OPTIONS describes the method as an `anyOf`
  of the variants the caller may send. A plain spec's
  `success_status(result, variant=None)` or
  `response_finalizer(response, variant=None)` passed `as_view()` on 0.9.0,
  since a defaulted parameter was never checked; each is now refused, as only
  a `DiscriminatedAction` offers `variant`.
- **OpenAPI documents a `DiscriminatedAction`.** The request is one component,
  `{View}_{action}_Request`, an `anyOf` over each variant's body (a serializer's
  `$ref`, or the inline schema of any other Validator); a variant taking no
  body adds no member, and where none takes one there is no request body, never
  an empty `anyOf`, as OPTIONS describes it. The responses are the variants'
  merged per status, one body where they agree and an inline `anyOf` where they
  differ, and a `400` always, since the discriminator may refuse. A variant with
  a body but no serializer (an array of rows) is now documented, which drfs left
  out of its component. Variants of one body are one member, in OpenAPI and in
  OPTIONS. Where two operations would give one component name two bodies (two
  classes of one name in different modules, or a route capture that changes a
  variant's body), the second is given inline as the same `anyOf` with a
  drf-spectacular warning, rather than refused. drfs' component was a `oneOf`;
  this one is an `anyOf`, since a member is open (the edge drops a key it does
  not know) and a body two variants accept is valid for both, which a `oneOf`
  would document as invalid.

### Changed

- **The floor on `django-service-specs` is 0.29.0**, for its `build_call_context`
  and `authorize_without_arguments`. The check a caller is judged by before the
  body is read, and that an `OPTIONS` answer shares, now asks through the second,
  with no change in what it answers.

### Fixed

- **The moving page and the codemod no longer say `OfflineContract` has no
  counterpart.** Its parts have seats: `field_audiences` is
  `SerializerPresenter(S, field_audiences=...)`, `url_kwargs` a `Parameter` in
  the selector's `reads=` (or a server-supplied argument where the model must
  never see the capture), `query_params` `shapes=` on the spec. The "Declaring
  a spec" table carries a row for each, and one for `ArgumentBinding`, whose
  choice the kernel's single argument namespace makes for the caller. The
  codemod's marker on a use of `OfflineContract` names those seats.

## [0.9.0] — 2026-11-05

### Changed

- **`get_queryset()` off `list` is DRF's own.** A viewset with a `list` spec
  answered that spec's set from `get_queryset()` to every action. Now it does
  so on `list` alone, and every other action reads the viewset's `queryset`,
  as on DRF's own viewset: a `retrieve`, a write, a `@selector_action`, a
  custom `@action` reading `self.get_queryset()`, and OPTIONS.
  `SelectorListView` answers its spec's set to a `GET` or `HEAD` alone. So a
  view under DRF's `DjangoModelPermissions` with no `queryset` attribute now
  raises DRF's own assertion off the list, where it used to read the model
  off the list spec's set: set `queryset` on it, as DRF asks. And the rows an
  action with no spec of its own reaches now come from `queryset`, no longer
  from the list selector: DRF's fallback `retrieve` (its `get_object()`) and a
  custom `@action` reading `self.get_queryset()` reach a row the list selector
  leaves out. A project that scoped a tenant in its list selector alone and
  relied on it for those actions scopes `queryset` too, or serves them with a
  spec.
- **A route capture is documented from the read its spec declares.** A spec
  viewset with no `queryset` gave drf-spectacular its model through the list
  spec's set; off `list` it now gives none. So where drf-spectacular finds no
  model and the path does not type the capture, the schema types it from the
  read the operation's spec declares for it (a retrieve's or a detail
  action's selector, a write's target selector, or the write's own `reads`),
  with the read's `help` as its description. A viewset with no `queryset`
  keeps its router's `{id}` an integer, with no warning, and needs no
  `queryset` for its schema; its description is now the read's `help`, where
  it was the model's primary key's. Where drf-spectacular finds a model, or a
  converter or regex types the capture, its answer stands.

### Fixed

- **A retrieve or a PATCH beside a list spec answers as its own spec says.**
  DRF's `DjangoModelPermissions` asks `get_queryset()` on every action, so
  beside a list spec with a required read a `retrieve`, a PATCH, a
  `@selector_action` or an OPTIONS (a CORS preflight) answered the list's
  400, or 403 where the list's own check refused. `SelectorListView`
  answered an OPTIONS, and a method it does not serve, the same way.
- **A list runs its selector once under `DjangoModelPermissions`.** The
  permission class's `get_queryset()` and the list each dispatched the spec.
  The list now presents the dispatch the permission class asked for, kept for
  that request alone.

## [0.8.1] — 2026-11-05

### Fixed

- **The page on moving from drfs names the changes that pass without an
  error.** A spec's rows are scoped by its selector alone: no action a spec
  serves takes its rows from `get_queryset()`, and `filter_backends` narrow
  only a `list`. So tenant scoping kept in a `get_queryset()` override or a
  filter backend no longer narrows an update or delete that drfs looked up
  through DRF's `get_object()`, and scoping kept in `get_queryset()` no longer
  narrows a `list`: the scoping moves into the selector. An eager-loading
  mixin overriding `get_queryset()` no longer loads a `list`'s rows, so the
  loading moves to the selector spec's `select_related`, `prefetch_related`
  or `extend_queryset`. A PATCH behind a `SerializerValidator` hands the service
  only the keys sent, as DRF does, so a service written for a whole body
  belongs on PUT or behind a validator that is not partial. Code reading a
  drfs spec's `output_serializer`, `input_serializer` or `permission_classes`
  through `getattr(..., None)` gets `None`; the page names the kernel's
  spellings. And a worked example takes a nested route's captures, marked
  `InputRequired` and `InputDescription` on an `Unpack[TypedDict]`
  signature, to `reads=` with `required=True` and `help=`, and shows the
  schema an agent is described by.

## [0.8.0] — 2026-11-05

### Added

- **A viewset's actions answer with their own status and finalizer.** A
  viewset's `success_status` and `response_finalizer` answered for every
  action, so actions answering differently needed a callable switching on
  `view.action`. Now `@service_action(spec, success_status=...,
  response_finalizer=...)` declares a decorated action's own, and a
  `get_<action>_success_status` or `get_<action>_response_finalizer` hook (a
  method, or an `int` for a status) an `action_specs` entry's. The most
  specific answers: the decorator's, the hook, the viewset's, then the
  action's default. `as_view()` asks each what it asks the viewset's, naming
  the action, and refuses a decorator value beside a hook for the same action;
  the OpenAPI schema documents the action's status. The viewset-wide
  attributes are unchanged. Before, the decorator's two keywords went to DRF's
  `@action`, which hands them to `as_view()` only under a router, unchecked by
  name; they are the action's own on every mount now.
- **A codemod for moving from drfs, in the repository, not the wheel.**
  `tools/drfs_codemod` rewrites a project's drfs 0.62.0 imports by the module
  each names, so a kernel name spelled like a drfs one is left alone, and
  turns each drfs `ServiceSpec` and `SelectorSpec` into the kernel's, its
  fields on their seats. A spec's `success_status` and `response_finalizer`
  move to the views in the same module serving it, for a spec bound to a
  module-level name; one built inline in a view is marked. Every site left (a read
  drfs took from a selector's signature, a `UrlKwarg` or `QueryParam` list, a
  name with no counterpart, an answer whose view is elsewhere) is marked with
  a `# drfs-codemod:` comment and reported as `path:line: reason`, and a
  second run changes nothing. Run from a clone with `PYTHONPATH=tools python
  -m drfs_codemod <paths>`; "Moving from djangorestframework-services" says
  what it does not do.

## [0.7.0] — 2026-11-05

### Changed

- **The OpenAPI schema documents the 422 only where a spec declares it, so
  every project's schema changes on upgrade.** `ServiceAutoSchema` documented
  the 422 of a plain `ServiceError` (`ServiceErrorSerializer`) on every
  service spec and every selector spec, though nothing in a spec says whether
  its service, selector, preconditions or providers raise one; a project whose
  code raises none published a status no route answers. Now an operation
  documents it only where the spec it serves declares it, with
  `metadata={"document_service_error": True}` (the key is exported as
  `django_spec_rest.openapi.SERVICE_ERROR_METADATA_KEY`); a value other than
  `True` or `False` is refused with `ImproperlyConfigured` when the schema is
  generated. Upgrading, a schema loses its 422s: declare the key on each spec
  that raises a plain `ServiceError` or an `AdditionalInputRequired`, declare
  `@extend_schema(responses={422: ServiceErrorSerializer})` on one view, or
  override the new public `ServiceAutoSchema.documents_service_error(spec)` in
  your schema class to return `True` and keep the 422 everywhere. A drfs
  spec's `document_service_error=True` moves into `metadata` under the same
  name. The runtime is unchanged: the edge still answers a plain
  `ServiceError` 422.
- **A viewset refuses at `as_view()` a router-mounted detail route whose row
  lookup does not read the lookup capture.** The capture a router builds
  (`lookup_url_kwarg`, else `lookup_field`) reaches a spec only as a parameter
  it declares, so a
  `retrieve` spec, a detail `@selector_action`, or an `update`,
  `partial_update`, `destroy` or detail `@service_action` whose
  `instance_selector_spec` declared no read of that name looked its row up
  without its key at every request. It is now refused when a router mounts
  the detail route (it hands `as_view()` `detail=True`), naming the viewset, the
  action, the capture and the read to declare. A project upgrading may see a
  router fail to build its routes: declare the read on the selector, or set
  `lookup_url_kwarg` to the name it reads. A viewset mounted by hand (a `me/`
  singleton) and a standalone view are not checked; their captures are the
  URLconf's.
- **A `SerializerPresenter`'s `serializer_context` callable is asked once for a
  list, not once per row.** A list view's page and a `many` service's return
  are presented through `presented_rows`, which asks the callable once and
  offers the rows under `page`, the name drfs gave them, and under the
  presenter's `value_keyword`; a callable batching a lookup over the page ran
  it once per row before, and one declaring `page` was never answered. The rows
  render as one `many=True` serializer, so a `Meta.list_serializer_class` runs,
  and the view's output hook is handed the whole set too. A project upgrading
  whose list or `many` callable declares `result` (or its `value_keyword`)
  expecting one row now receives the list of rows: read the row from the
  serializer's own `to_representation` instead, or batch over the list. `page`
  is always a list of the rows, never a queryset: as drfs did on a paginated
  view, and unlike drfs on an unpaginated one, where it handed the selector's
  queryset, so a provider calling `page.values_list(...)` or another queryset
  method must work over the list instead. One value presents as before.
- **A caller the spec's checks refuse is refused before its body's shape is
  checked**, as DRF and drfs ask permission classes before the handler reads
  the body. An anonymous caller sending an incomplete or ill-typed body to a
  guarded write was answered 400 with the field errors, and a signed-in caller
  the checks refuse 400 as well; both are now answered as for a well-formed
  body, 401 with the authenticator's challenge or 403. A read's query string
  is judged the same way. A request failing its shape is judged on no
  arguments, and a check that cannot answer without them keeps the kernel's
  order, so its caller is still told the 400 first. A client that sent 401 and
  403 to sign-in no longer shows an anonymous visitor field errors. The
  OPTIONS answer asks the same question, so it describes a method to exactly
  the callers whose incomplete request is told what it lacks; it now also
  leaves a create out for a caller whose scope check refuses the create, and
  a spec declaring no permissions fails an incomplete write with
  its configuration error, as a well-formed write already did.
- **The moving page lists the four 400 answers a drfs client sees change.**
  An output serializer's list `ValidationError` is keyed under
  `non_field_errors` (a page too), DRF's field messages are the kernel's on a
  JSON body, a body that is no object answers `{"detail": ...}`, and a numeric
  string is still taken for an integer field while a number is no string.
  Documentation only: the behaviour stands.

### Fixed

- **A list of the package's 403 or 401 body on a paginated view no longer lets
  a project's serializer of the same name pass.** `PermissionDeniedSerializer(many=True)`
  or `NotAuthenticatedSerializer(many=True)` is a plain `ListSerializer`, which
  the "never a list" override on the two classes does not reach. On a
  paginated list view, as its `200` or, under `ENABLE_LIST_MECHANICS_ON_NON_2XX`,
  as its `403` or `401`, drf-spectacular's pagination naming descended to the
  body and asked for its component name, which registered and armed the
  reserved component without taking a `$ref` of it. A project's serializer of
  the name resolved next was then documented by the package's `{detail}` body
  instead of refused. The two bodies now build a list class of their own whose
  pagination name is the body's, so the naming stops at the list; a list of
  the body as a list view's `200` is documented as a page of them, as before.

## [0.6.1] — 2026-11-04

### Fixed

- **A `PATCH` request of the package's 403 or 401 body no longer lets a
  project's serializer of the same name pass.** Under drf-spectacular's
  default `COMPONENT_SPLIT_PATCH`, `PermissionDeniedSerializer` or
  `NotAuthenticatedSerializer` declared as a `PATCH` request is documented as
  its partial twin, `PatchedPermissionDenied` or `PatchedNotAuthenticated`,
  but it also registered the reserved `PermissionDenied` or
  `NotAuthenticated` component, unreferenced, and left it marked as the
  package's for the next class resolved under that name. A project's
  serializer of the name resolved after it was documented by the package's
  body, with only drf-spectacular's warning of two components of one name,
  rather than refused. The partial twin is now resolved as the
  `COMPONENT_SPLIT_REQUEST` twin is: the package registers nothing under its
  reserved name for it, so the project's serializer is refused wherever the
  package's body is documented under the name (by a package view, or by a
  response declaring it) and is the project's own component otherwise.

## [0.6.0] — 2026-11-04

### Added

- **The 403 and 401 bodies are exported, for a project to declare.**
  `PermissionDeniedSerializer` and `NotAuthenticatedSerializer`, from
  `django_spec_rest.openapi`, are the `PermissionDenied` and
  `NotAuthenticated` components a spec's own refusals document. Declared with
  `@extend_schema(responses=...)` on any view, one of the package's or a
  project's own on drf-spectacular's `AutoSchema`, either is the package's
  component, in whichever order the views are resolved; before, the only
  bodies were private, and declaring one on a project's view beside a package
  view failed generation with `ImproperlyConfigured`. A project's serializer
  under either name is still refused, now also where the project's comes
  first and the package's body is declared on drf-spectacular's own schema.
  The OpenAPI guide's "Refusals your project configures" declares them in
  place of a serializer of the project's.
- **`enable_openapi()` sets the package's schema on the action mixins.**
  `ServiceCreateMixin`, `ServiceUpdateMixin`, `ServiceDestroyMixin`,
  `SelectorListMixin` and `SelectorRetrieveMixin` now carry
  `ServiceAutoSchema` as the views and `ServiceViewSet` do, so a project's
  `GenericViewSet` composed of them documents its specs with no `schema` of
  its own, where a mixin comes before `GenericViewSet` in its bases. With
  `GenericViewSet` first, DRF's own `schema` wins, and a `@service_action` on
  a bare `GenericViewSet` has no mixin: both still set `schema` or
  `DEFAULT_SCHEMA_CLASS`, as the OpenAPI guide says.

### Changed

- **The action mixins' schema wins over a project's `DEFAULT_SCHEMA_CLASS`.**
  A `GenericViewSet` composed of `ServiceCreateMixin`, `ServiceUpdateMixin`,
  `ServiceDestroyMixin`, `SelectorListMixin` or `SelectorRetrieveMixin`, with
  a mixin before `GenericViewSet`, took the project's `DEFAULT_SCHEMA_CLASS`
  before; now that `enable_openapi()` sets `ServiceAutoSchema` on the mixins
  it takes that, even where the default is a subclass of it. Setting
  `schema = ProjectSchema()` on the viewset keeps the subclass.

- **The OpenAPI guide says a `$ref` written to a reserved name is refused on
  any view.** `@extend_schema(responses={403: {"$ref":
  "#/components/schemas/PermissionDenied"}})` on a package view is refused
  with `ImproperlyConfigured`, as on a project's view: the project asserts a
  name whose body it does not own. Generation answered so before; a test now
  holds it.

- **The anonymous caller's 401 is described as a check's denial
  throughout.** The test docstrings and comments that said a check
  *refusing* a caller nobody authenticated now say *denying* (answering
  `False` to) it, where a check raising `NotPermitted` itself is answered as
  raised, 403; the OpenAPI guide's 401 bullet and the docstrings beside it
  are reflowed, and a garbled clause in that bullet repaired. Wording only;
  nothing answers differently.

### Fixed

- **A paginated list's 403 and 401 stay the one refusal under
  `ENABLE_LIST_MECHANICS_ON_NON_2XX`.** With that drf-spectacular setting on,
  a paginated `SelectorListView` with checks documented its 403 as
  `PaginatedPermissionDeniedList`, and the pagination naming left the
  package's `PermissionDenied` or `NotAuthenticated` component armed, so a
  project's serializer of that name resolved next was not refused.
  `PermissionDeniedSerializer` and `NotAuthenticatedSerializer` now declare
  they are never a list.

- **The schema leaves out a viewset method answered 405 for want of a spec.**
  drf-spectacular documented every method a router maps, so a
  `ServiceViewSet` route serving some spec documented a `create`, `update`,
  `partial_update` or `destroy` with no spec behind it, which answers 405 and
  which `Allow` and OPTIONS already left out; generation also printed
  `exception raised while getting serializer` for it. `ServiceAutoSchema`
  now excludes such a method by the rule `Allow` reads: a viewset with no
  `destroy` spec documents no `DELETE`, one with a `partial_update` spec alone
  no `PUT`. The `list` and `retrieve` fallbacks, a handler the viewset defines
  itself, a route serving no spec and the standalone views are documented as
  before.

## [0.5.0] — 2026-11-04

### Changed

- **A kernel permission check asks a caller nobody authenticated to sign in.**
  Where a `PermissionCheck` the dispatched spec declares denies (answers
  `False` to) a caller the request's authenticators did not recognise, the
  view answers DRF's
  `NotAuthenticated`, as it already did for an adapted DRF class and as drfs
  did: 401 with the first authenticator's `WWW-Authenticate` challenge, or 403
  "Authentication credentials were not provided." where that authenticator
  sends none. It was 403 with the check's message. A signed-in caller, and any
  caller of a view with no authenticator, is still refused 403 with the
  check's message. This holds at the class-level check and at the one asked of
  the row the spec's own lookup finds. A service's own `NotPermitted`, an
  inner `dispatch` a service makes whose check refused, and a check that
  raises `NotPermitted` itself rather than answering `False`, are not the
  caller's to sign in for and stay 403 with their message, as DRF answers a
  permission class that raises `PermissionDenied`.
- **A `many` spec's rows are named as dispatch names them.** A
  `get_service_kwargs` value named like a row's field pins that field in every
  row. The row's names are now asked of any Validator the way the kernel's
  `dispatch` asks it, handing the call's context to one whose `parameters()`
  declares `call_context`, where only a `SerializerValidator` was handed it
  before. A Validator naming other fields for a call than outside one had the
  value left out of the rows.
- **The schema documents a kernel check's 401.** Every operation whose spec
  declares a check other than `Unrestricted` now documents the 401 (the
  `NotAuthenticated` component) where the view's first authenticator sends a
  `WWW-Authenticate` challenge, whatever kind of check it is. Before, only an
  operation with a `DRFPermissionCheck` among its checks documented it, since
  a kernel `PermissionCheck` denying an anonymous caller was answered 403.
  Behind an authenticator sending no challenge, or on a view with none, the
  operation still documents the 403 alone.
- **The `django-service-specs` floor is 0.24.0**, the release carrying
  `validator_parameters` and `PermissionCheckDenied`.

### Fixed

- **A project's component under a name the package keeps is refused on any
  view.** `ValidationErrors`, `PermissionDenied` and `NotAuthenticated` are the
  bodies of a spec's 400, 403 and 401. A serializer of the project's under one
  of them, on a view of the project's own on drf-spectacular's `AutoSchema`
  resolved after the package's refusal, got drf-spectacular's warning alone,
  and its request and response were documented by the refusal's body.
  `enable_openapi()` now inserts a postprocessing hook,
  `reserved_components_hook`, first in drf-spectacular's `POSTPROCESSING_HOOKS`
  (before the project's own, once, so a project hook that copies the schema
  cannot hide the package's references from it), which refuses any reference to these names
  the package did not write with `ImproperlyConfigured`, naming the operation,
  component or webhook that holds it. A document in which no spec uses one of
  the names leaves it to the project. The generated schema is unchanged.
- **The `ServiceError` component is described for a client.** Its
  `description` in a generated schema was the serializer's docstring, written
  for the API reference, so the published document carried mkdocs
  cross-reference syntax and a private class name. It now says what the body
  is: why the service could not complete the call, under `detail`, and the
  values still needed, under `schema`. No other component the package
  registers carried either.

## [0.4.0] — 2026-11-03

### Added

- **A permission-checked operation documents its 403.** Every operation whose
  spec declares a check other than `Unrestricted` documents a 403, the body of
  a check's denial and of a principal who cannot act (`{"detail": ...}`, the
  `PermissionDenied` component). Where one of the checks is a
  `DRFPermissionCheck` (directly, or in `AllOf` or `AnyOf`) and the view's
  first authenticator sends a `WWW-Authenticate` challenge, the 401 that check
  answers a caller nobody authenticated with is documented beside it (the
  `NotAuthenticated` component). The wire is unchanged. As with
  `ValidationErrors`, a serializer that components under either name
  (`PermissionDeniedSerializer`, `NotAuthenticatedSerializer`) is refused with
  `ImproperlyConfigured` naming the `component_name` that fixes it, rather than
  re-pointing every 403 or 401 at its fields.
- **Serializers for the refusals a service raises.** Which refusals a service
  raises is the project's to declare, with drf-spectacular's
  `@extend_schema(responses=...)`. `django_spec_rest.openapi` now exports a
  schema-only serializer per body `map_service_error` sends:
  `ServiceValidationErrorSerializer` (400: a list, or an object by name, whose
  members are a message, a list or an object of the same shape, so a list of
  mappings too), `ServiceNotFoundSerializer` (404),
  `ServiceConflictSerializer` (409, with `code` named and not required) and
  `ActionUnavailableSerializer` (409, `code` required), beside the existing
  `ServiceErrorSerializer` (422). The recipe is in the OpenAPI page. Importing
  `django_spec_rest.openapi` still does not import drf-spectacular;
  `ServiceValidationErrorSerializer` is rendered once `enable_openapi()` has
  run.

### Changed

- **`@extend_schema(responses=...)` on a spec's operation adds to what the
  spec documents.** drf-spectacular answers a declared `responses` as it is,
  so declaring a 404 dropped the operation's success body, its 400 and its
  422. A mapping of statuses is now laid over the spec's responses: a status
  declared replaces the spec's at that status, and a declared `2xx` replaces
  every success status the spec documents. A bare serializer passed as
  `responses=` is the success body at the status the route answers with, where
  it was documented at drf-spectacular's default for the method (a create
  view's `POST` as a 200); where the spec answers a 204, which the edge sends
  with no body, it stays the no-content 204. A project that declared every
  response itself now sees the spec's others beside them. Only drf-spectacular's
  own `extend_schema` is merged this way: a project's `ServiceAutoSchema`
  subclass overriding `get_response_serializers` is answered as it writes it
  (a status it leaves out stays out), and under `extend_schema` it is the base
  the declared statuses are laid over. Generation writes nothing to the shared
  schema a class-level `extend_schema` leaves on the view, so two threads
  generating at once do not interfere.

## [0.3.1] — 2026-11-03

### Fixed

- **The documented 400 admits what the edge sends.** The `ValidationErrors`
  component allowed a field's list of messages, a nested object or a row's
  index, and `{"detail": ...}` stood beside it. A service raising
  `ServiceValidationError` is answered with DRF's `ValidationError(detail)`, so
  the body can also be a bare list (`["Bad."]`) or an object with a string
  leaf (`{"name": "Bad."}`), which failed the schema and could be refused by a
  strict generated client. The 400 now has the list as a third alternative, and
  a leaf may be a string; the wire is unchanged.
- **A selector's refusals are documented.** A selector operation documented
  neither the 400 nor the 422 the edge answers it with. It now documents a 422
  (the selector, a precondition or a provider can raise a plain `ServiceError`)
  and, where the spec takes a parameter (a read, a shape or a filter), the 400
  of its refusal, in the same body as a service spec's. The 422 body also
  names the `schema` an `AdditionalInputRequired` carries (an object, not
  required), which the `ServiceError` component allowed but did not name, on
  service specs too.
- **A serializer taking the `ValidationErrors` component's name is refused.**
  drf-spectacular only warns of two components of one name and keeps one for
  both, so since 0.3.0 a serializer that resolved to that name had its own
  response documented by the 400's body, or the 400 by its fields. Generating
  the schema now raises `ImproperlyConfigured` naming the serializer and the
  `component_name` that fixes it, so such a project renames the component
  (a `SpectacularAPIView` answers 500 until it does). It is refused where the
  serializer is resolved through this package's schema, or before the 400; a
  view of the project's own on drf-spectacular's `AutoSchema`, resolved after
  the 400, still gets only drf-spectacular's warning.
- **Mounting a view makes no class.** Since 0.3.0 every `as_view()` checked
  the view against a subclass named like the author's, and since 0.1.0 a
  viewset's made one more per `action_specs` entry, so a project's
  `__init_subclass__`, metaclass or subclass registry saw classes it never
  wrote. The checks now read the
  author's class through the keywords instead, and ask the same questions;
  refusals still name the author's class.
- **A selector asking for more input is answered with its schema as raised.**
  A kernel selector, precondition or provider raising `AdditionalInputRequired`
  on `SelectorListView`, `SelectorRetrieveView`, or a `@selector_action` on
  DRF's own `GenericViewSet` or `ViewSet` (or with `GenericViewSet` listed
  before `ActionSerializerResolver`), answered the 422 with every leaf of
  the schema a string (`"default": "False"`, `"maximum": "3"`). It now serves
  the schema as raised, as the mutation views and `@service_action` do.

## [0.3.0] — 2026-11-03

### Security

- **A spec handed to `as_view(spec=...)` meets every check the same class
  attribute meets at `as_view()`.** It was never checked, and a mutation view
  still dispatched it. So do the other keywords those checks read:
  `success_status`, `response_finalizer`, `filter_backends`, and a viewset's
  `action_specs`. A selector view handed `as_view(spec=...)` no
  longer falls through to DRF's own `queryset`, which served every row without
  asking the spec's `permissions`.

### Changed

- **An adapted DRF permission class refusing a caller nobody authenticated
  asks them to sign in, as a DRF view asks.** When a DRF permission class in
  `DRFPermissionCheck` returns `False`, a caller the request's authenticators
  did not recognise gets DRF's `NotAuthenticated`: 401 with the first
  authenticator's `WWW-Authenticate` when it sends one, otherwise 403
  "Authentication credentials were not provided.". A signed-in caller, and any
  caller of a view with no authenticator, still gets 403 with the class's own
  `message`. So `DRFPermissionCheck` can now raise `DRFNotAuthenticated`, which
  is not a `PermissionDenied`: code catching `PermissionDenied` around such a
  dispatch should catch the kernel's `NotPermitted`, their common base (see
  `docs/moving-from-drfs.md`). A kernel `PermissionCheck`'s refusal is still the
  kernel's 403 with its message: the kernel raises the same `NotPermitted` for
  a permission check's denial, a service's own and a refused inner dispatch's,
  so asking that caller to sign in waits for the kernel to mark the denial.
  Off HTTP the refusal is still the kernel's `NotPermitted`.
- **The OpenAPI request body of a `SerializerValidator` spec agrees with
  OPTIONS.** Where the spec's `input_data` fills or may fill one of the
  serializer's fields, the body no longer lists the fields `input_data` always
  fills and no longer requires the ones it may fill. It is documented under a
  component of its own named from the serializer's, such as `TaskLessOwner` or
  `TaskLessOwner__OptionalNote` (the rule is in the OpenAPI page), so the class
  name a generated client uses changes for such specs. A spec whose
  `input_data` reaches none of the serializer's fields keeps its component.
- **A decorated action's spec is seed-checked when its viewset is mounted.**
  On a viewset built on this package's bases (`ServiceViewSet`,
  `SelectorViewSet`, or a class on their mixins or `ActionSerializerResolver`),
  `as_view()` runs the kernel's seed check on every `@service_action` and
  `@selector_action` spec against the viewset's `pool_seeds`. A spec needing a
  keyword nothing fills, such as a seed the viewset does not register, is
  refused there with `ImproperlyConfigured` naming the action and the seed,
  where a `@service_action` used to mount and fail its first request with
  `TypeError`; so a mount that passed may now be refused. A `@selector_action`
  reading a seed its viewset registers is now served: it is no longer checked
  against the kernel's default seeds when the method is decorated. A
  `@service_action` on a viewset overriding `get_service_kwargs` or
  `get_<action>_service_kwargs` is not asked, as a standalone view with one is
  not. On DRF's own `GenericViewSet` or `ViewSet` nothing runs the check, and a
  missing seed is the action's first request's `TypeError`.

### Added

- **`permission_denied`** (`django_spec_rest.service_specs.permission_denied`):
  the refusal DRF's `APIView.permission_denied` would raise for a request, as
  the kernel's denial. `DRFPermissionCheck` raises it for an adapted DRF class.

### Fixed

- **A kernel dispatch a service makes of the view's own spec for another
  principal is described afresh, not as the request's own call.** A
  `SerializerValidator` declares `parameters(call_context=)`: the request's
  call builds its serializer once under the view, and an inner dispatch gets
  its own description. A service handing its own `call_context` to the inner
  dispatch is still described as the request's call.
- **`SelectorListView` and `SelectorRetrieveView` serve a spec handed to
  `as_view(spec=...)`**, and a mutation view answers with an `as_view()`
  keyword's `success_status` and `response_finalizer`.
- **A Validator's refusal is documented as the 400 the edge sends, not a
  422.** Every kind of Validator (`SerializerValidator`, `DataclassValidator`,
  another raising `InvalidArguments`) answers DRF's field errors under a 400,
  which the generated schema never mentioned. A spec with a Validator now
  documents that 400, with the errors in a `ValidationErrors` component (or
  `{"detail": ...}` for a body that is no object). The 422 is the status of a
  plain `ServiceError` raised by the service, a precondition or a provider, so
  it is now documented on every service spec, with or without a Validator.

## [0.2.1] — 2026-11-02

### Fixed

- **The docs and the example no longer say every view refuses a missing seed
  at `as_view()`.** A `@service_action` spec is not seed-checked at mount, so
  a seed its viewset does not register is its first request's `TypeError`;
  the recipe, the concepts page and the invoices example now say so.
- **The concepts page no longer lists a nested selector's `permissions`
  among the `as_view()` checks.** The kernel refuses it when the `ServiceSpec`
  is built.
- **The `@selector_action` limit is worded to what it covers.** The spec is
  checked against the kernel's default seeds when the method is decorated, so
  the callables the kernel's seed check reads (the selector, its providers and
  its affordance conditions) cannot name a seed the viewset registers; a
  permission check naming one is served.

## [0.2.0] — 2026-11-02

### Added

- **`pool_seeds` on every view and viewset**: the kernel `PoolSeeds` the
  spec's callables are resolved with, `DEFAULT_POOL_SEEDS` unless set as a
  class attribute or as `as_view(pool_seeds=...)`. A spec whose service,
  selector, provider, permission check, precondition or affordance condition
  reads a registered seed (`DEFAULT_POOL_SEEDS.extend(frozen=...)`) is served
  by a view registering it; until now no view could register one. A
  `@service_action` or `@selector_action` dispatches with its viewset's, and
  the OpenAPI request body and the `OPTIONS` answer
  describe what a caller sends under the same seeds, so a read a registered
  seed fills is offered in neither, and `OPTIONS` asks a permission check
  naming a registered seed rather than failing.

### Changed

- **`as_view()` checks a spec against the view's `pool_seeds`**, so an
  affordance condition or a precondition requiring a seed the view does not
  register is refused with `ImproperlyConfigured` naming the seed. A spec that
  mounted before may now be refused: every request reaching that callable
  failed with `TypeError`. A view overriding `get_service_kwargs` or a
  per-action `get_<action>_service_kwargs` is still not checked, its
  conditions and preconditions included. `@selector_action` checks its spec
  when the method is decorated, against the kernel's default seeds.
- **The seeds a target's checks resolved are handed on to the run.** Where a
  write's row is found by its spec's own target selector, the kernel's
  `resolve_target` and `dispatch` are handed the view's one `pool_seeds` and
  the call's context, and `dispatch` takes the values the lookup's checks were
  offered, so each seed a permission check names is resolved once per call
  rather than twice.
- **Requires `django-service-specs` 0.23.0.** A nested selector
  (`instance_selector_spec`, `collection_selector_spec`, `output_selector_spec`)
  that declares `permissions` is now refused by the kernel when the
  `ServiceSpec` is built, rather than by the view at `as_view()`.
- **OpenAPI and OPTIONS ask the caller for what dispatch demands of it.** The
  OpenAPI request body of a spec whose Validator is not a
  `SerializerValidator`, and the `actions[POST]` and `actions[PUT]` schemas of
  OPTIONS, are the kernel's `spec_caller_input_schema` less the target lookup's
  parameters and the route's captures. A key a provider may fill or decline is
  offered and no longer required; OPTIONS now requires none of a `partial`
  spec's fields, as OpenAPI already did; and each row of a `many` spec leaves
  out a field its typed `input_data` fills and no longer requires one it may
  fill.

## [0.1.0] — 2026-10-31

The first release. Every change below is against the previous package's
0.62.0, and [Moving from djangorestframework-services](https://artui.github.io/django-spec-rest/moving-from-drfs/)
lists each with what a project rewrites.

### Changed

- **Renamed.** The distribution is `django-spec-rest` and the importable
  package is `django_spec_rest`.
- **The views, viewsets and decorators serve the kernel's own specs.** `spec`,
  `action_specs`, `@service_action` and `@selector_action` take a
  `django_service_specs` `ServiceSpec` or `SelectorSpec`, run through the
  kernel's `dispatch`. DRF enters a spec through `SerializerValidator`,
  `SerializerPresenter` and `DRFPermissionCheck`.
- **The package root exports 29 names, none of them the kernel's.** A kernel
  name is imported from `django_service_specs`.
- **A write's target is its spec's own selector, never `get_object()`.**
  `as_view()` refuses an update or delete spec that declares no target.
- **The query string is read by the kernel's flat reader.** A blank filter or
  declared read is absent rather than a 400; a multiple-choice filter and a
  typed array split on a comma; a key no parameter declares is dropped.
- **One serializer context per request.** The input serializer, the output
  serializer and the service's `call_context` share one dict, so a key
  `validate()` writes reaches the service and the output serializer.
- **A form body is read leniently and a JSON body strictly.** A form's `"on"`,
  blank checkbox and prefixed spellings (`v.tenant`, `tags[0]`) are read as
  DRF reads them; a JSON body is checked against the declared types as sent.
- **A view hook's value outranks the validated value.** A key
  `get_service_kwargs` returns that the serializer declares writable reaches
  the service as the hook's value.
- **OPTIONS describes a route from its specs.** It runs no stage of a spec,
  `actions[METHOD]` is a JSON Schema object, and `Allow` names only the
  methods a spec serves.
- **`as_view()` refuses a `success_status` callable or `response_finalizer`
  that takes `**kwargs` beside a name the view cannot supply.** `**kwargs` is
  handed the names the view has and no others, so such a callable raised
  `TypeError` on every request, after the service had committed.
- **A `success_status` callable or `response_finalizer` with a
  positional-only parameter that has no default is refused at `as_view()`.**
  Every value is handed by keyword, so such a parameter was never supplied and
  the callable raised `TypeError` on every request; one with a default is left
  to it.
- **A bare `DispatchError` answers 400**, where it answered 500.
- **A `many` spec with an `output_selector_spec` presents the re-read's
  rows.**
- **Bulk and row refusals are worded by the kernel.**
- **The route's format suffix wins for `format`** over an overriding
  `get_serializer_context()`.
- **OpenAPI describes a `filter_set`'s parameters by the kernel's
  `filter_set_parameters`.**
- **`DRFPermissionCheck` takes `route_reads=` alone**; `url_kwargs=` and
  `query_params=` are gone, and the offline request's query string is empty.
- **`as_view()` refuses `permissions` on a nested selector**, which the kernel
  never asks: the spec being served is what authorizes.
- **The DRF refusal classes are `DRFInvalidArguments`, `DRFNotPermitted` and
  `DRFPrincipalUnavailable`.**

### Security

- **A kernel dispatch a service makes for another principal** is validated and
  described under the offline request for that principal, no longer under the
  view's request and view of the call being served. Another principal means
  another principal object: the same user fetched again counts as another.
  One exception, listed under the moving page's known limits: a service
  dispatching the view's own spec for another principal still gets the
  parameter set described under the view's request.
- **A target selector's filter and reads come from the route and the query
  string, never the body**, so a body value cannot choose an update's or a
  delete's row or set its lookup's `filter_set` scope.
- **A `kwargs` provider key naming a validator field is refused**, on a
  single-object spec and on a `many` spec's row fields alike, pointing at
  `input_data=`, which validates the value: a typed provider's when the view
  is built, an untyped one's on the request. Such a value reached the service
  unvalidated.

### Removed

- **`get_selector_kwargs`** on `SelectorListView`, `SelectorRetrieveView` and
  the two selector viewset mixins. A view that defines it, or the per-action
  `get_<action>_selector_kwargs`, beside a kernel spec is refused at
  `as_view()`: a selector's keywords come from the spec's own `kwargs`
  provider.
- **The previous package's declaration types**: `ServiceSpec`, `SelectorSpec`,
  `PolymorphicServiceSpec`, `UrlKwarg`, `QueryParam`, `ArgumentBinding`,
  `OfflineContract`, `TargetGuard` and the input markers. A kernel spec
  declares its reads, shapes, providers and permissions itself.
- **`dispatch_spec` and `adispatch_spec`**, the `jsonschema/`, `audience/` and
  `registry/` modules, and every re-export of a kernel name.
- **`JsonSchemaRegistry`'s `filters` and `python_types` rules.** A kernel spec
  types a `filter_set`'s filters through the kernel's `filter_set_parameters`
  and each read through its own `Parameter`, so neither rule has anything to
  type, and passing either is a `TypeError`. `fields` is the one rule left.
- **The `startserviceapp` management command** and its app template.
- **The package is no longer a Django app.** It has no models, migrations,
  templates, static files or URLs, so it needs no `INSTALLED_APPS` entry.

[Unreleased]: https://github.com/Artui/django-spec-rest/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/Artui/django-spec-rest/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/Artui/django-spec-rest/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/Artui/django-spec-rest/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/Artui/django-spec-rest/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/Artui/django-spec-rest/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/Artui/django-spec-rest/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/Artui/django-spec-rest/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/Artui/django-spec-rest/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Artui/django-spec-rest/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Artui/django-spec-rest/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/Artui/django-spec-rest/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Artui/django-spec-rest/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/Artui/django-spec-rest/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Artui/django-spec-rest/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Artui/django-spec-rest/compare/v0.0.0...v0.1.0
