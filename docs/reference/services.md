# Services

## Protocols

Each Protocol is parameterised by input, instance (where applicable), and
result. `**extras` is typed `Any`, so the framework's kwargs pool flows
through without the service having to declare each key. Strict-typed
extras live on the user's function signature via `**extras: Unpack[YourKw]`
— see [Typing services and selectors](../typing.md) for the full pattern.

::: django_spec_rest.services.create_service.CreateService

::: django_spec_rest.services.update_service.UpdateService

::: django_spec_rest.services.delete_service.DeleteService

## Default model service factories

### `create_model`

::: django_spec_rest.services.create_model.create_model

### `update_model`

::: django_spec_rest.services.update_model.update_model

### `delete_model`

::: django_spec_rest.services.delete_model.delete_model

### `acreate_model`

::: django_spec_rest.services.acreate_model.acreate_model

### `aupdate_model`

::: django_spec_rest.services.aupdate_model.aupdate_model

### `adelete_model`

::: django_spec_rest.services.adelete_model.adelete_model

### `delete_collection`

::: django_spec_rest.services.delete_collection.delete_collection

### `adelete_collection`

::: django_spec_rest.services.adelete_collection.adelete_collection

## Decorators

::: django_spec_rest.implements.implements

## Helpers

### `call_service`

::: django_spec_rest.services.call_service.call_service

### `acall_service`

::: django_spec_rest.services.acall_service.acall_service
