# Selectors

## Protocols

Each Protocol is parameterised on input / instance / result types only;
`**extras` is typed `Any`. Strict-typed extras live on the user's function
signature via `**extras: Unpack[YourKw]` — see
[Typing services and selectors](../typing.md) for the full pattern.

::: django_spec_rest.selectors.selector.Selector

::: django_spec_rest.selectors.async_selector.AsyncSelector

::: django_spec_rest.selectors.list_selector.ListSelector

::: django_spec_rest.selectors.retrieve_selector.RetrieveSelector

## Helpers

### `call_selector`

::: django_spec_rest.selectors.call_selector.call_selector

### `acall_selector`

::: django_spec_rest.selectors.acall_selector.acall_selector

## Dispatch

::: django_spec_rest.selectors.utils
