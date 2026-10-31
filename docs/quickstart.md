# Quickstart

A resource served on a viewset: list, retrieve, create and update an invoice.
The [example project](https://github.com/Artui/django-spec-rest/tree/main/examples)
is this page, finished and tested.

## 1. Services and selectors

Plain callables. A service names the values it needs by keyword: `data` is the
validated input, `instance` the row a write targets. A refusal is one of the
kernel's errors, which the view answers with its HTTP status.

```python
from django_service_specs import ServiceConflict

from invoices.models import Invoice


def create_invoice(*, data):
    return Invoice.objects.create(**data)


def update_invoice(*, instance, data):
    if instance.status != Invoice.STATUS_DRAFT:
        raise ServiceConflict("Only a draft invoice can be changed.")  # 409
    for name, value in data.items():
        setattr(instance, name, value)
    instance.save()
    return instance


def list_invoices():
    return Invoice.objects.all()


def get_invoice(*, pk):
    return Invoice.objects.filter(pk=pk).first()  # None answers 404
```

## 2. Serializers

Ordinary DRF serializers: one validates a body, one renders a row.

```python
from rest_framework import serializers


class InvoiceInput(serializers.Serializer):
    customer = serializers.CharField(max_length=200)
    amount_cents = serializers.IntegerField(min_value=0)
    notes = serializers.CharField(required=False, allow_blank=True)


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ("id", "customer", "amount_cents", "notes", "status")
```

## 3. Specs

Each spec is the kernel's. The serializers fill its `validator` and
`presenter` seats. The kernel refuses to dispatch a spec that declares no
`permissions`; `Unrestricted()` says the operation is open to every caller.

```python
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)

from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator

OPEN = (Unrestricted(),)
PRESENTER = SerializerPresenter(InvoiceSerializer)
BY_PK = Parameters.of(Parameter("pk", "integer", required=True))

LIST_SPEC = SelectorSpec(
    kind=SelectorKind.LIST, selector=list_invoices, permissions=OPEN, presenter=PRESENTER
)
RETRIEVE_SPEC = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=get_invoice,
    reads=BY_PK,
    permissions=OPEN,
    presenter=PRESENTER,
)
CREATE_SPEC = ServiceSpec(
    service=create_invoice,
    validator=SerializerValidator(InvoiceInput),
    permissions=OPEN,
    presenter=PRESENTER,
)
UPDATE_SPEC = ServiceSpec(
    service=update_invoice,
    validator=SerializerValidator(InvoiceInput),
    # The row an update writes is found by its own selector, reading ``pk``
    # from the route. A nested selector declares no permissions.
    instance_selector_spec=SelectorSpec(
        kind=SelectorKind.RETRIEVE, selector=get_invoice, reads=BY_PK
    ),
    permissions=OPEN,
    presenter=PRESENTER,
)
```

## 4. The viewset and its routes

```python
from rest_framework.routers import DefaultRouter

from django_spec_rest import ServiceViewSet


class InvoiceViewSet(ServiceViewSet):
    action_specs = {
        "list": LIST_SPEC,
        "retrieve": RETRIEVE_SPEC,
        "create": CREATE_SPEC,
        "update": UPDATE_SPEC,  # PATCH falls back to it, validated partially
    }


router = DefaultRouter()
router.register("invoices", InvoiceViewSet, basename="invoice")
urlpatterns = router.urls
```

That serves:

| Request | Answer |
| --- | --- |
| `GET /invoices/` | the rows, rendered by `InvoiceSerializer` |
| `GET /invoices/1/` | one row, or 404 |
| `POST /invoices/` | 201 with the created row, or 400 keyed by field |
| `PUT /invoices/1/` | every required field validated |
| `PATCH /invoices/1/` | only the fields sent validated; 409 for a sent invoice |
| `DELETE /invoices/1/` | 405: no spec serves it, and `Allow` leaves it out |
| `OPTIONS /invoices/1/` | the `PUT` body as a JSON Schema, with no stage of a spec run |

## 5. The same spec off HTTP

A spec is not tied to its route. The kernel's `dispatch` runs it for a
principal and a dict of arguments:

```python
from django_service_specs import dispatch

result = dispatch(
    UPDATE_SPEC,
    principal=user,
    arguments={"pk": 1, "customer": "Acme Ltd", "amount_cents": 4200},
)
result.value  # the updated Invoice
```

See [Calling a spec off HTTP](recipes/off-http-inputs.md).
