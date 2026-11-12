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

The callable's keys are written last, over the request's and the view hooks' keys,
so a key it returns for `request` or `view` replaces theirs. A key whose value is
`UNSET` is not written, and the earlier value stands.

## What a presenter's callable receives

A presenter's `serializer_context` callable declares what it reads by name:
`request`, `view`, `user`, `call_context`, a registered seed, and the value
being rendered.

| Rendering | Asked | The value, by name |
| --- | --- | --- |
| one value: a service's output, a retrieve | once | under `value_keyword`: `result` by default, `instance` where the presenter names it so |
| a list: a page's rows, a `many` service's return | once for the list, not once per row | the rows under `page`, and under `value_keyword` too |

So a callable on a list view can batch one lookup over the page's rows and
hand the answer to every row through the context:

```python
def comment_counts(*, page):
    ids = [post.pk for post in page]
    counts = dict(
        Comment.objects.filter(post_id__in=ids).values_list("post_id").annotate(n=Count("id"))
    )
    return {"comment_counts": counts}


class PostSerializer(serializers.ModelSerializer):
    comments = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = ("id", "title", "comments")

    def get_comments(self, post):
        return self.context["comment_counts"].get(post.pk, 0)


POSTS = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=list_posts,
    permissions=OPEN,
    presenter=SerializerPresenter(PostSerializer, serializer_context=comment_counts),
)
```

The query runs once a page, whatever the page size. `page` holds the rows
being rendered, already evaluated, as a list: on a paginated view only the
page's rows, never DRF's `Page` object, and never a queryset to filter
further. A presenter with `value_keyword=None` offers the rows under `page`
alone. A `many` service's callable declaring `result` receives its whole
return, as the view's `get_output_serializer_context(result)` does.

The rows render as one `many=True` serializer, so a `Meta.list_serializer_class`
and its `to_representation` run on a list as behind a DRF view. Its answer
keeps one row per value, in order: affordances are added to each row by its
position, and a list of another length is refused.

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
no request in its context: `self.context["request"]` is `None` there, so a
`get_fields()` or `__init__` that dereferences it raises `AttributeError`;
guard such a read.
[`base_serializer_context`][django_spec_rest.service_specs.base_serializer_context.base_serializer_context]
and
[`build_offline_context`][django_spec_rest.service_specs.build_offline_context.build_offline_context]
build that context for code of your own that renders a serializer outside a
view.
