# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This package continues `djangorestframework-services`, whose history it
carries; releases up to 0.62.0 are in
[that package's changelog](https://github.com/Artui/djangorestframework-services/blob/main/CHANGELOG.md).

## [Unreleased]

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
  lookup does not read the lookup capture.** The capture a router builds (`lookup_url_kwarg`,
  else `lookup_field`) reaches a spec only as a parameter it declares, so a
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

[Unreleased]: https://github.com/Artui/django-spec-rest/compare/v0.7.0...HEAD
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
