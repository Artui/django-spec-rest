# Field schema rules

A serializer field the seats have no row for, or one whose row says the wrong
thing, is declared by a rule: a field class and the JSON Schema fragment a field
of it is. The rules live in the kernel's
[`JsonSchemaRegistry`][django_service_specs.types.json_schema_registry.JsonSchemaRegistry],
which `django_spec_rest.types.json_schema_registry` re-exports unchanged, and
`SerializerValidator` and `SerializerPresenter` read them before their own table.

Here is a field that keeps a string, such as `AB-12`, while inheriting from
`IntegerField`. By its class it is an `integer`, so the kernel's shape check
answers a JSON body's `"AB-12"` with `400 {"code": ["Expected an integer."]}`
before the serializer sees it:

```python
from rest_framework import serializers


class LooseIntField(serializers.IntegerField):
    def to_internal_value(self, data):
        return data
```

## The project's rules

A rule for a field the project owns belongs to the project, not to each seat.
The kernel's `SERVICE_SPECS_FIELD_SCHEMA_REGISTRY` setting names the project's
registry by dotted path:

```python
# myproject/field_schemas.py
from django_service_specs import JsonSchemaRegistry

FIELD_SCHEMAS = JsonSchemaRegistry().extend(
    fields=[(LooseIntField, {"type": "string"})],
)
```

```python
# settings.py
SERVICE_SPECS_FIELD_SCHEMA_REGISTRY = "myproject.field_schemas.FIELD_SCHEMAS"
```

Every `SerializerValidator` and `SerializerPresenter` then declares a
`LooseIntField` a `string`, at any depth: a nested serializer's field, a
`many=True` row's, a `ListField`'s element. The body's `"AB-12"` reaches the
serializer, and the parameters and the output say `string`. The kernel's
`FormValidator` reads the same setting, so one rule serves a form and a
serializer.

The setting is read whenever a seat declares its fields, never cached, so
`override_settings` reaches a spec built and dispatched before it.

## A seat's own rules, and which rule wins

A seat still takes `json_schema_registry=`, for a rule only it needs:

```python
from django_spec_rest.types.json_schema_registry import DEFAULT_JSON_SCHEMA_REGISTRY

money = DEFAULT_JSON_SCHEMA_REGISTRY.extend(fields=[(MoneyField, {"type": "string"})])
SerializerValidator(InvoiceIn, json_schema_registry=money)
```

The rules of both registries are matched through the field class's MRO:

- **The most specific class wins**, whichever registry holds its rule. A
  project rule for `LooseIntField` beats a seat rule for `IntegerField`, and a
  seat rule for `LooseIntField` beats a project rule for `IntegerField`.
- **For one class, the seat's rule wins** over the project's.
- **Within one registry, two rules for one class are answered by the first**,
  so a rule `extend()` prepends wins. A rule for a base listed before one for
  its subclass no longer answers the subclass: the subclass's own rule does.
- **An empty seat registry adds nothing** and still reads the project's.

`project_registry=False` opts one seat out of the project's rules; its own
`json_schema_registry=` still applies:

```python
SerializerPresenter(LegacyOut, project_registry=False)
```

The variant of a spec one request dispatches (a `PATCH`'s partial copy, a form
body's lenient one) keeps the seat's registry and its opt-out.

## What a rule can state

A fragment becomes the field's `Parameter` or `OutputField` through the kernel's
[`fragment_keywords`][django_service_specs.schema.fragment_keywords.fragment_keywords]:
`type`, `format` and `enum` where the kernel can state them, a parameter's bounds,
and any other keyword as advertised-only `json_schema_extra`. The field's own
`required`, `allow_null`, `help_text` and `label` stand beside the fragment.
