# django-spec-rest

Serve [django-service-specs](https://artui.github.io/django-service-specs/)
over Django REST Framework.

A kernel spec declares an operation once: the callable that runs it, the
arguments it reads, who may call it, how its input is validated and how its
result is presented. `django-spec-rest` serves that spec on a DRF view or
viewset, and lets DRF fill three of its seats: a serializer validates the
input (`SerializerValidator`), a serializer renders the result
(`SerializerPresenter`), and DRF permission classes decide who may call it
(`DRFPermissionCheck`). The same spec runs off HTTP through the kernel's own
`dispatch`, and on any other transport that serves kernel specs.

## What you get

- **Views and viewsets that take a kernel spec**: `ServiceCreateView`,
  `ServiceUpdateView`, `ServiceDeleteView`, `SelectorListView`,
  `SelectorRetrieveView`, `ServiceViewSet`, `SelectorViewSet`, the per-action
  mixins, and `@service_action` / `@selector_action` for custom routes.
- **One reading of a request**: route captures, the query string and the body
  become the spec's arguments by the kernel's rules, and a refusal comes back
  as DRF's answer with DRF's status.
- **DRF's seats**: serializers for input and output, permission classes for
  authorization, with one serializer context per request.
- **OPTIONS and OpenAPI read off the spec**: the opt-in `drf-spectacular`
  integration describes each route's request and response.

## Install

```bash
pip install django-spec-rest
# or, with uv:
uv add django-spec-rest
```

The package is not a Django app and needs no `INSTALLED_APPS` entry. A spec's
`filter_set` needs the kernel's `filter` extra
(`pip install "django-service-specs[filter]"`), and the OpenAPI integration
needs `pip install "django-spec-rest[spectacular]"`.

## Where to next

- **[Quickstart](quickstart.md)**: a resource served on a viewset.
- **[Concepts](concepts.md)**: what the edge reads from a request, and how each
  refusal is answered.
- **[Recipes](recipes/index.md)**: custom actions, hooks, permissions,
  filtering, serializer context, calling a spec off HTTP.
- **[Moving from djangorestframework-services](moving-from-drfs.md)**: the
  import map and every change a client sees.
- **[Reference](reference/index.md)**: the API, generated from the source.

## Compatibility

| Axis | Range |
|---|---|
| Python | 3.10 – 3.14 |
| Django | 4.2, 5.0, 5.1, 5.2, 6.0 |
| DRF | ≥ 3.14 |

CI runs the full Python × Django matrix with 100% coverage gating, minus
the cells the upstream version-support docs already rule out (e.g. Django
6.0 only runs on Python 3.12+).
