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
`SelectorRetrieveView`, `ServiceViewSet` and `SelectorViewSet`, so every
subclass inherits it; a class setting `schema` itself keeps its own.
Importing `django_spec_rest.openapi` does not import `drf-spectacular`; only
this call does.

## What a route documents

- **The request body** is a `SerializerValidator`'s serializer, under
  drf-spectacular's component name for the class, built partial where the
  route validates partially (a `PATCH`, or a spec declaring `partial`).
  Where the spec's `input_data` fills or may fill one of its fields, the body
  is a component of its own (see below). A `many` spec takes a list of its
  rows. Any other validator is the kernel's
  `spec_caller_input_schema`, less the target lookup's parameters and the
  route's captures, which never come from the body: a key the server fills is
  not offered, and one a provider may fill or decline is offered and not
  required. A `many` spec's rows are read the same way, by what its
  `input_data` fills in every row.
- **The response body** is a `SerializerPresenter`'s serializer, or another
  presenter's output schema, a list where the spec presents rows. A spec with
  no presenter documents no content; a selector spec with none keeps the
  view's `serializer_class`, which renders it.
- **The status** is the view's `success_status` where it is an `int`, over the
  action's default. A body documented under 204 is documented as the 200 it is
  served as, with a 204 beside it where the spec can present nothing.
- **A 400** is documented wherever the spec declares a validator, because that
  is the status a validator's refusal gets, whichever kind refused
  (`SerializerValidator`, `DataclassValidator` or another validator raising the
  kernel's `InvalidArguments`). Its body is the `ValidationErrors` component:
  the errors by name, as DRF sends them, each a list of messages, or an object
  for a nested field, or for a list its rows' errors keyed by the row's index
  (a `many` spec's rows sit under its `many_argument`); the whole call's
  messages are under `non_field_errors`. A body that is no object is refused
  with `{"detail": ...}`, so the 400 is either that component or the
  `ServiceError` one.
- **A 422** is documented on every service spec, whether or not it has a
  validator. It is not a validator's refusal: it is a plain `ServiceError`
  raised by the service, a precondition or a provider, which no spec can rule
  out. Its body is `{"detail": ...}` (an `AdditionalInputRequired` carrying a
  schema adds a `schema` key beside it).
- **A `filter_set`'s query parameters**, on a list operation, are the kernel's
  `filter_set_parameters`.

`ServiceErrorSerializer`, a single `detail` field, is the body of that 422 and
of the 400 for a body that is no object, under the `ServiceError` component.

User-supplied `@extend_schema` annotations always win, and
`@extend_schema(parameters=...)` merges over the filter parameters as it does
for a view-level `FilterSet`.

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
