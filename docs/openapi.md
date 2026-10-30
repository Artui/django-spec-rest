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
  route validates partially (a `PATCH`, or a spec declaring `partial`). A
  `many` spec takes a list of its rows. Any other validator is the kernel's
  JSON Schema of the parameters the body carries.
- **The response body** is a `SerializerPresenter`'s serializer, or another
  presenter's output schema, a list where the spec presents rows. A spec with
  no presenter documents no content; a selector spec with none keeps the
  view's `serializer_class`, which renders it.
- **The status** is the view's `success_status` where it is an `int`, over the
  action's default. A body documented under 204 is documented as the 200 it is
  served as, with a 204 beside it where the spec can present nothing.
- **A 422** is documented wherever the spec declares a validator.
- **A `filter_set`'s query parameters**, on a list operation, are the kernel's
  `filter_set_parameters`.

`ServiceErrorSerializer`, a single `detail` field, is the body of that 422,
under the `ServiceError` component.

User-supplied `@extend_schema` annotations always win, and
`@extend_schema(parameters=...)` merges over the filter parameters as it does
for a view-level `FilterSet`.

## Not documented

A selector spec's declared reads are not documented as query parameters, nor
the affordance envelope a spec declaring affordances renders, nor the `null`
body of an `allow_none` retrieve. Add them with `@extend_schema` where a
client needs them.
