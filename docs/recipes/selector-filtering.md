# Filter a selector with `filter_set`

A kernel `SelectorSpec` takes a `django-filter` `FilterSet` on `filter_set`.
The kernel applies it to the queryset the selector returns, with the
`FilterSet`'s filters as the spec's arguments, so the same filters apply over
HTTP, off HTTP and on any other transport. It needs the kernel's `filter`
extra:

```bash
pip install "django-service-specs[filter]"
```

```python
import django_filters
from django_service_specs import SelectorKind, SelectorSpec


class InvoiceFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=Invoice.STATUS_CHOICES)
    customer = django_filters.CharFilter(lookup_expr="icontains")

    class Meta:
        model = Invoice
        fields = []


LIST_SPEC = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=list_invoices,
    filter_set=InvoiceFilter,
    permissions=OPEN,
    presenter=PRESENTER,
)
```

## Over HTTP

A list route reads the filters off the query string, by the kernel's flat
reader:

| Request | Answer |
| --- | --- |
| `GET /invoices/?status=sent` | the sent invoices |
| `GET /invoices/?customer=acm` | the invoices whose customer contains `acm` |
| `GET /invoices/?status=` | every invoice: a blank filter is absent |
| `GET /invoices/?status=lost` | 400, keyed `status` |

A multiple-choice filter takes repeated keys or one comma-separated value
(`?st=ann,bob`), and a typed array splits on a comma.

`filter_set` replaces `DjangoFilterBackend`: a list view declaring both is
refused at `as_view()`, since the queryset would be filtered twice. The view's
other filter backends, and its paginator, still apply to the set the spec
read.

## Values the server supplies

The kernel has one argument namespace, so a `kwargs` provider's value named
like a filter reaches the filter, over the query string's. That is the place
for a scope the client must not choose.

## A write's target

A `filter_set` on an update's or a delete's `instance_selector_spec` or
`collection_selector_spec` reads the route and the query string only, never
the body: a body value cannot set the scope that picks the row a write
changes.

## A retrieve

A retrieve spec runs its own selector rather than DRF's `get_object()`, so the
view's `filter_backends` do not apply to it: a tenant-scoping backend in
`DEFAULT_FILTER_BACKENDS` narrows the list and not the lookup. Scope the
selector's queryset, or declare the rule as the spec's `filter_set`.
