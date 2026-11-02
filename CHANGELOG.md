# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This package continues `djangorestframework-services`, whose history it
carries; releases up to 0.62.0 are in
[that package's changelog](https://github.com/Artui/djangorestframework-services/blob/main/CHANGELOG.md).

## [Unreleased]

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

[Unreleased]: https://github.com/Artui/django-spec-rest/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Artui/django-spec-rest/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Artui/django-spec-rest/compare/v0.0.0...v0.1.0
