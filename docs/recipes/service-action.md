# Viewsets and custom actions

## The standard actions

`ServiceViewSet` serves `list`, `retrieve`, `create`, `update`,
`partial_update` and `destroy`, each from its entry in `action_specs`.
`SelectorViewSet` serves `list` and `retrieve`. An action with no entry falls
back to DRF's own behaviour for the reads (`get_queryset()`, `get_object()`)
and answers 405 for the writes, and `Allow` leaves an unserved write out.

```python
from django_spec_rest import ServiceViewSet


class InvoiceViewSet(ServiceViewSet):
    action_specs = {
        "list": LIST_SPEC,
        "retrieve": RETRIEVE_SPEC,
        "create": CREATE_SPEC,
        "update": UPDATE_SPEC,
        # "partial_update" is optional: PATCH falls back to "update",
        # validated partially. Declare it to give PATCH a spec of its own,
        # or alone for a PATCH-only route.
    }
```

An entry under `list` or `retrieve` must be a `SelectorSpec`, and under a write
key a `ServiceSpec`. An entry under a key no action dispatches is refused at
`as_view()`, since nothing would ask its permissions: a custom route takes its
spec through a decorator.

## A custom write: `@service_action`

```python
from typing import Any

from django_spec_rest import ServiceViewSet, service_action


class InvoiceViewSet(ServiceViewSet):
    action_specs = {...}

    @service_action(SEND_SPEC, detail=True, methods=["post"])
    def send(self, request: Any, pk: Any = None) -> None:
        """Mark a draft as sent."""
```

The method's body never runs: the decorator supplies the handler, and the
method gives DRF's `@action` its name. `detail`, `methods`, `url_path`,
`url_name` and any other keyword go to DRF's `@action`. On a detail route the
row is the spec's own target selector's, read from the route's `pk`, never
`get_object()`'s. The answer is the spec's presenter's, under the viewset's
`success_status` (200 by default).

## A custom read: `@selector_action`

```python
from django_spec_rest import SelectorViewSet, selector_action


class InvoiceViewSet(SelectorViewSet):
    @selector_action(OVERDUE_SPEC)
    def overdue(self, request: Any) -> None:
        """Invoices past their due date."""
```

The spec's `kind` sets the route's shape: a `LIST` spec is a collection action,
paginated where the viewset paginates, and a `RETRIEVE` spec a detail action,
answering 404 for a miss or `null` under `allow_none`.

## Composing your own viewset

Each standard action is a mixin over `GenericViewSet`, so a viewset takes only
the actions it serves:

```python
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import (
    ActionSerializerResolver,
    SelectorListMixin,
    ServiceCreateMixin,
)


class InboxViewSet(ServiceCreateMixin, SelectorListMixin, ActionSerializerResolver, GenericViewSet):
    action_specs = {"list": INBOX_SPEC, "create": POST_MESSAGE_SPEC}
```

`ActionSerializerResolver` answers `get_serializer_class()` per action: a write
spec's input serializer where the viewset sets no `serializer_class`, which
DRF's browsable API asks to draw its forms, and the viewset's
`serializer_class` otherwise.

## A standalone view

A single route needs no viewset:

```python
from django_spec_rest import SelectorListView


class SentInvoiceListView(SelectorListView):
    spec = SENT_SPEC
```
