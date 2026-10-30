# Serializer context

## One dict per request

Over HTTP the view builds one context dict per request, holding DRF's
`request`, `view` and `format`, the viewset's `action`, and every key the
view's `get_serializer_context()` adds. The input serializer, the output
serializer and the service's `call_context` are all handed that same dict, as
one serializer validating and rendering in a stock `ModelViewSet` sees one
context:

```python
from rest_framework import serializers


class InvoiceInput(serializers.Serializer):
    amount_cents = serializers.IntegerField(min_value=0)

    def validate(self, attrs):
        if attrs["amount_cents"] == 0:
            self.context.setdefault("warnings", []).append("The amount is zero.")
        return attrs


class InvoiceSerializer(serializers.ModelSerializer):
    warnings = serializers.SerializerMethodField()

    def get_warnings(self, invoice):
        return list(self.context.get("warnings", []))


def create_invoice(*, data, call_context):
    call_context.get("warnings")  # the same list
```

The example project asserts the warning `validate()` writes is rendered in the
answer.

`format` is the route's: on a route with a format suffix, `format` is the
suffix even where an overriding `get_serializer_context()` answers another
value for it.

## Keys a spec adds

`SerializerValidator(serializer_context=...)` and
`SerializerPresenter(serializer_context=...)` take a callable returning keys for
their serializer. Over HTTP the validator's keys are written into the request's
one dict, so the service and the output serializer see them too.

```python
CREATE_SPEC = ServiceSpec(
    service=create_invoice,
    validator=SerializerValidator(InvoiceInput, serializer_context=lambda: {"currency": "EUR"}),
    presenter=SerializerPresenter(InvoiceSerializer),
    permissions=OPEN,
)
```

A presenter's `serializer_context` callable runs once for each row it renders,
so for a list it runs once per row, not once for the page: a callable that
queries runs its query per row. Load what every row needs in the selector
(`select_related`, `prefetch_related`, `annotations`) instead.

## Keys a view adds

A mutation view's hooks layer keys over DRF's context, view-wide then per
action:

| Serializer | View-wide | Per action |
| --- | --- | --- |
| input | `get_input_serializer_context()` | `get_<action>_input_serializer_context()` |
| output | `get_output_serializer_context()` | `get_<action>_output_serializer_context()` |

Both view-wide hooks default to `get_serializer_context()`. A selector spec's
presenter is not handed the per-action output hook: declare its context on its
`SerializerPresenter`.

## Off HTTP

Dispatched with no request, a seat builds its serializer over an offline
request and view for the principal, so a serializer reading
`self.context["request"].user` while it validates reads the principal. Off
HTTP the kernel also describes the serializer's fields before the call, with
no request in its context: a `get_fields()` or `__init__` reading
`self.context["request"]` raises there, so guard such a read.
[`base_serializer_context`][django_spec_rest.service_specs.base_serializer_context.base_serializer_context]
and
[`build_offline_context`][django_spec_rest.service_specs.build_offline_context.build_offline_context]
build that context for code of your own that renders a serializer outside a
view.
