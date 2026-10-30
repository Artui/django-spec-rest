# Recipes

Task-shaped how-tos. Each assumes the [Quickstart](../quickstart.md) and
[Concepts](../concepts.md). What a spec itself declares (preconditions,
affordances, queryset shaping, nested relations, bulk writes, a spec registry
shared by several transports) is the
[kernel's documentation](https://artui.github.io/django-service-specs/).

- **[Viewsets and custom actions](service-action.md)**: `action_specs`,
  `@service_action`, `@selector_action`, and composing a viewset from the
  per-action mixins.
- **[View hooks and providers](extra-kwargs.md)**: the server's values for a
  service, on the spec and on the view, and which outranks which.
- **[DRF permission classes](permissions.md)**: `DRFPermissionCheck` on a spec,
  over HTTP and off it.
- **[Filter a selector with `filter_set`](selector-filtering.md)**: a
  `django-filter` `FilterSet` read off the query string.
- **[Serializer context](serializer-context.md)**: one context dict per
  request, and the keys a spec or a view adds.
- **[Calling a spec off HTTP](off-http-inputs.md)**: the kernel's `dispatch`
  over a spec a route serves.
