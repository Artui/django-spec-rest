# django-spec-rest

[![CI](https://github.com/Artui/django-spec-rest/workflows/tests/badge.svg)](https://github.com/Artui/django-spec-rest/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/django-spec-rest.svg)](https://pypi.org/project/django-spec-rest/)
[![Python versions](https://img.shields.io/pypi/pyversions/django-spec-rest.svg)](https://pypi.org/project/django-spec-rest/)
[![Django versions](https://img.shields.io/pypi/djversions/django-spec-rest.svg)](https://pypi.org/project/django-spec-rest/)
[![Docs](https://img.shields.io/badge/docs-artui.github.io-blue.svg)](https://artui.github.io/django-spec-rest/)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Artui/django-spec-rest/gh-pages/coverage.json)](https://github.com/Artui/django-spec-rest/actions/workflows/tests.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License](https://img.shields.io/pypi/l/django-spec-rest.svg)](LICENSE)

A service / selector layer for Django REST Framework.
Serve [django-service-specs](https://github.com/Artui/django-service-specs)
kernel specs over Django REST Framework.

A kernel spec declares an operation once: the callable that runs it, the
arguments it reads, who may call it, how its input is validated and how its
result is presented. `django-spec-rest` serves that spec on a DRF view or
viewset, and lets DRF fill three of its seats: a serializer validates the
input (`SerializerValidator`), a serializer renders the result
(`SerializerPresenter`), and DRF permission classes decide who may call it
(`DRFPermissionCheck`). The same spec runs off HTTP through the kernel's own
`dispatch`, and on any other transport that serves kernel specs.

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

**Full documentation:** <https://artui.github.io/django-spec-rest/>

Coming from `djangorestframework-services`? The
[moving page](https://artui.github.io/django-spec-rest/moving-from-drfs/) has the
import map and every change a client sees.

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

## Quick start

A service, a selector and two serializers, all plain:

```python
from rest_framework import serializers

from invoices.models import Invoice


def create_invoice(*, data):
    return Invoice.objects.create(**data)


def list_invoices():
    return Invoice.objects.all()


class InvoiceInput(serializers.Serializer):
    customer = serializers.CharField(max_length=200)
    amount_cents = serializers.IntegerField(min_value=0)


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ("id", "customer", "amount_cents", "status")
```

Kernel specs with DRF in their seats, served on a viewset:

```python
from django_service_specs import SelectorKind, SelectorSpec, ServiceSpec, Unrestricted
from rest_framework.routers import DefaultRouter

from django_spec_rest import ServiceViewSet
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator

OPEN = (Unrestricted(),)
PRESENTER = SerializerPresenter(InvoiceSerializer)


class InvoiceViewSet(ServiceViewSet):
    action_specs = {
        "list": SelectorSpec(
            kind=SelectorKind.LIST,
            selector=list_invoices,
            permissions=OPEN,
            presenter=PRESENTER,
        ),
        "create": ServiceSpec(
            service=create_invoice,
            validator=SerializerValidator(InvoiceInput),
            permissions=OPEN,
            presenter=PRESENTER,
        ),
    }


router = DefaultRouter()
router.register("invoices", InvoiceViewSet, basename="invoice")
urlpatterns = router.urls
```

`GET /invoices/` answers the rows rendered by `InvoiceSerializer`;
`POST /invoices/` answers 201 with the created row, or 400 keyed by field. The
kernel refuses to dispatch a spec that declares no `permissions`, so
`Unrestricted()` says the operation is open to every caller. The
[quickstart](https://artui.github.io/django-spec-rest/quickstart/) carries this
on to retrieve, update, OPTIONS and a call off HTTP.

## Example project

[`examples/`](examples/) is a runnable Django project on one resource, with a
test per behaviour: a spec on a viewset and on a standalone view, a filter read
off the query string, OPTIONS on a detail route, a refusal of each status, a
`DRFPermissionCheck` over HTTP and through the kernel's plain `dispatch`, and a
key one serializer writes into the shared context that another renders.

```bash
cd examples
python manage.py migrate
python manage.py runserver
```

## Compatibility

| Axis | Range |
|---|---|
| Python | 3.10 – 3.14 |
| Django | 4.2, 5.0, 5.1, 5.2, 6.0 |
| DRF | ≥ 3.14 |

CI runs the full Python × Django matrix with 100% coverage gating.

## Status

Pre-1.0. See [`CHANGELOG.md`](CHANGELOG.md) for the release history.

## License

MIT.
