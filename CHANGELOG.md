# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This package continues `djangorestframework-services`, whose history it
carries; releases up to 0.62.0 are in
[that package's changelog](https://github.com/Artui/djangorestframework-services/blob/main/CHANGELOG.md).

## [Unreleased]

## [0.4.0] — 2026-11-03

### Added

- **A permission-checked operation documents its 403.** Every operation whose
  spec declares a check other than `Unrestricted` documents a 403, the body of
  a check's denial and of a principal who cannot act (`{"detail": ...}`, the
  `PermissionDenied` component). Where one of the checks is a
  `DRFPermissionCheck` (directly, or in `AllOf` or `AnyOf`) and the view's
  first authenticator sends a `WWW-Authenticate` challenge, the 401 that check
  answers a caller nobody authenticated with is documented beside it (the
  `NotAuthenticated` component). The wire is unchanged.
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
  view's `POST` as a 200). A project that declared every response itself now
  sees the spec's others beside them.

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

[Unreleased]: https://github.com/Artui/django-spec-rest/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/Artui/django-spec-rest/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/Artui/django-spec-rest/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Artui/django-spec-rest/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/Artui/django-spec-rest/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Artui/django-spec-rest/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Artui/django-spec-rest/compare/v0.0.0...v0.1.0
