# Link affordances to their routes

A selector spec declaring `affordances` answers, on every row it presents,
whether each operation is available. Set `link_routes` on the view, and each
entry also says where and how to call it: `href` and `method`.

```python
from django_service_specs import SelectorKind, SelectorSpec, SpecLink, SpecRegistry

from django_spec_rest import SelectorListView

# Names are URL pattern names, as `reverse` takes them ("books:rename").
INVOICE_ROUTES = SpecRegistry()
INVOICE_ROUTES.register("invoice-detail", UPDATE_SPEC)
INVOICE_ROUTES.register("invoice-send", SEND_SPEC)

LINKED_SPEC = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=list_invoices,
    permissions=OPEN,
    presenter=PRESENTER,
    affordances={
        "update": SpecLink(UPDATE_SPEC, arguments={"pk": "id"}),
        "send": SpecLink(SEND_SPEC, arguments={"pk": "id"}),
    },
)


class LinkedInvoiceListView(SelectorListView):
    spec = LINKED_SPEC
    link_routes = INVOICE_ROUTES
```

```json
{
  "id": 7,
  "customer": "Acme",
  "affordances": {
    "update": {"available": true, "href": "https://api.example/invoices/7/", "method": "PUT"},
    "send": {"available": true, "href": "https://api.example/invoices/7/send/", "method": "POST"}
  }
}
```

The example project serves this as `GET /linked-invoices/`.

## What each part does

- **`link_routes`** is a kernel `SpecRegistry` whose names are URL pattern
  names. It is a class attribute or an `as_view(link_routes=...)` keyword on
  `SelectorListView`, `SelectorRetrieveView` and the viewsets (their `list`,
  `retrieve` and `@selector_action` reads). `None`, the default, leaves every
  entry its availability answer alone. `as_view()` refuses anything else.
- **The target's name** is the registry's `name_of`, matched by identity, so
  the spec an affordance names, or one `replace` displaced, is found.
- **`href`** is DRF's `reverse` of that name, run per response and never at
  import or `as_view()`, so the registry may be declared before the URLconf
  loads. Its kwargs are the link's required reads alone: the target's
  selector reads a caller must supply (the `required` the kernel's
  `row_links` gives each link, an instance selector's `pk`, say), each with the
  row's value for the field it binds to. A bound read that is not required, such as a body field, is left
  out. A service with no target selector has no required reads, so its route
  takes no kwargs. It is absolute, as DRF's hyperlinked fields are, and
  follows the request's versioning scheme.
- **`method`** comes from the view the route resolves to: the first of `POST`,
  `PUT`, `PATCH`, `DELETE` that serves the target, looked up once per route
  per response. A router's detail
  route serves an `"update"` spec under both `PUT` and `PATCH`, so it is `PUT`;
  a dedicated `"partial_update"` entry is `PATCH`. A
  `DiscriminatedAction` serves each of its variants.

## When an entry has no `href`

The entry keeps `available`, and its `code` and `reason`, and leaves out `href`
and `method` together, when:

- the registry does not name the target;
- the name does not reverse with the row's required reads;
- the view at that route serves the target under no method;
- the row lacks a field one of the row's links binds a required read to (a
  serializer that leaves `id` out of some rows, say). The kernel refuses the
  whole row, so every entry on it keeps its answer alone. This holds only for a
  presenter that declares its output, whose fields `link_bindings` has checked;
  with no output, the missing field may be a misnamed one, and it raises.

An unavailable entry still carries its `href`: availability and address are
separate answers. A binding the kernel refuses (a required read nothing binds)
raises `ImproperlyConfigured` on the first response, as `link_bindings` does;
run the kernel's `check_links` as a system check to refuse it at startup.

One URL pattern name can stand for one spec only. A router's detail route
serving both an update and a destroy can link one of them.

## OpenAPI

With `enable_openapi()`, a selector whose presenter declares its rows documents
each row as its own schema plus the `affordances` object, every entry with
`available` (and `code` and `reason` where it declares conditions). An entry
whose target `link_routes` names also documents `href` (`format: uri`) and
`method`, neither required.
