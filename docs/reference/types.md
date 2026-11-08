# Types

The shapes this package owns: the view protocol and its hook chain, the
DRF-typed authoring helpers, the offline request and view a caller off HTTP
hands a serializer, and the serializer-field marking and schema registry the
seats read.

## Discriminated actions

`DiscriminatedAction` serves one write action at one URL through one of several
kernel specs, chosen by the request. One spec per route stays the default; this is
the opt-in for an endpoint that must keep one URL. It is this package's alone, never a
kernel spec: agents and MCP register each variant on its own.

::: django_spec_rest.types.discriminated_action.DiscriminatedAction

## Views and hooks

::: django_spec_rest.types.service_view.ServiceView

::: django_spec_rest.types.view_hooks.ViewHooks

::: django_spec_rest.types.http_extras.HttpExtras

## Off HTTP

::: django_spec_rest.types.offline_context.OfflineContext

::: django_spec_rest.types.offline_http_request.OfflineHttpRequest

::: django_spec_rest.types.offline_service_view.OfflineServiceView

## The transport

::: django_spec_rest.types.rest_transport.REST_TRANSPORT

## Serializer fields

::: django_spec_rest.types.field_marking.MARKING

::: django_spec_rest.types.json_schema_registry.JsonSchemaRegistry

::: django_spec_rest.types.json_schema_registry.DEFAULT_JSON_SCHEMA_REGISTRY
