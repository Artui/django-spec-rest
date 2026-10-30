# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This package continues `djangorestframework-services`, whose history it
carries; releases up to 0.62.0 are in
[that package's changelog](https://github.com/Artui/djangorestframework-services/blob/main/CHANGELOG.md).

## [Unreleased]

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
- **A target selector's filter and reads come from the route and the query
  string, never the body**, so a body value cannot choose an update's or a
  delete's row or set its lookup's `filter_set` scope.
- **A `kwargs` provider key naming a validator field is refused**, pointing at
  `input_data=`, which validates the value: a typed provider's when the view
  is built, an untyped one's on the request.
- **`as_view()` refuses `permissions` on a nested selector**, which the kernel
  never asks: the spec being served is what authorizes.
- **The DRF refusal classes are `DRFInvalidArguments`, `DRFNotPermitted` and
  `DRFPrincipalUnavailable`.**

### Security

- **A kernel dispatch a service makes for another principal** is validated and
  described under the offline request for that principal, no longer under the
  view's request and view of the call being served. Another principal means
  another principal object: the same user fetched again counts as another.

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

[Unreleased]: https://github.com/Artui/django-spec-rest/compare/v0.0.0...HEAD
