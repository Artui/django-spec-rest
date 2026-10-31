# Example: invoices

A minimal Django project serving kernel specs from
[`django-service-specs`](https://github.com/Artui/django-service-specs) over
Django REST Framework with `django-spec-rest`, on a single resource.

## What it demonstrates

| File | Pattern |
|---|---|
| [`invoices/models/__init__.py`](invoices/models/__init__.py) | A single `Invoice` model |
| [`invoices/services/__init__.py`](invoices/services/__init__.py) | Plain-callable services refusing with the kernel's `ServiceConflict` (409) and `ServiceError` (422) |
| [`invoices/selectors/__init__.py`](invoices/selectors/__init__.py) | Plain-callable selectors, and `InvoiceFilter`, the `django-filter` `FilterSet` the list spec reads off the query string |
| [`invoices/serializers/__init__.py`](invoices/serializers/__init__.py) | `InvoiceInput`, whose `validate()` writes a warning into its `context`, and `InvoiceSerializer`, which renders the warning from the same dict |
| [`invoices/views/__init__.py`](invoices/views/__init__.py) | Kernel `ServiceSpec`s and `SelectorSpec`s with a `SerializerValidator`, a `SerializerPresenter` and a `DRFPermissionCheck`; `InvoiceViewSet`, a `ServiceViewSet` serving list, retrieve, create and update from `action_specs` plus `POST /invoices/<pk>/send/` through `@service_action`; and `SentInvoiceListView`, one selector spec on a standalone `SelectorListView` |
| [`invoices/urls.py`](invoices/urls.py) | The router, and the standalone view's route |
| [`invoices/tests/__init__.py`](invoices/tests/__init__.py) | One test class per behaviour below |

The tests assert, one class each:

| Class | Behaviour |
|---|---|
| `SpecOnAViewSetTests` | A create validated by the serializer and presented by another; a retrieve reading `pk` from the route; a `PATCH` validating only what it sends, and reaching the routed row whatever `pk` its body names; a `PUT` validating every required field |
| `OffHttpTests` | The viewset's update spec run through the kernel's `dispatch` with no request |
| `SpecOnAViewTests` | A standalone `SelectorListView` answering its selector's rows |
| `FilterOffTheQueryStringTests` | `?status=` and `?customer=` narrowing the list through the spec's `filter_set`; a blank `?status=` read as absent; a value the filter refuses answered 400 under its name |
| `OptionsOnADetailRouteTests` | `Allow` naming only the methods a spec serves (no `DELETE`, which answers 405); `actions["PUT"]` a JSON Schema object leaving out the route's `pk`; no query run, so no stage of the spec |
| `ARefusalOfEachStatusTests` | 400 keyed by field, 403 from a `DRFPermissionCheck`, 404 for a missing row on a read and on a write, 409 from `ServiceConflict`, 422 from any other `ServiceError` |
| `DRFPermissionCheckTests` | One `DRFPermissionCheck([IsAuthenticated])` admitting an authenticated client over HTTP, and admitting a user and refusing an anonymous principal with the kernel's `NotPermitted` through the kernel's plain `dispatch` |
| `SharedSerializerContextTests` | A key the input serializer's `validate()` writes, rendered by the output serializer |

## Run it

```bash
cd examples
python manage.py migrate
python manage.py runserver
```

Then exercise the endpoints:

```bash
# Create
curl -X POST http://localhost:8000/invoices/ \
  -H "Content-Type: application/json" \
  -d '{"customer": "Acme", "amount_cents": 4200, "notes": "Thanks!"}'

# List, optionally filtered
curl http://localhost:8000/invoices/
curl "http://localhost:8000/invoices/?status=draft&customer=acm"

# Retrieve, and describe the detail route
curl http://localhost:8000/invoices/1/
curl -X OPTIONS http://localhost:8000/invoices/1/

# Update (PATCH validates only the fields sent)
curl -X PATCH http://localhost:8000/invoices/1/ \
  -H "Content-Type: application/json" \
  -d '{"notes": "Net 30"}'

# Send: refused with 403 here, since the action asks DRF's IsAuthenticated
# and the project configures no authentication
curl -X POST http://localhost:8000/invoices/1/send/

# The standalone view
curl http://localhost:8000/sent-invoices/
```

## Run the tests

```bash
python manage.py test invoices
```

From the repository root, `make examples` runs the same suite, as CI does on
every pull request.
