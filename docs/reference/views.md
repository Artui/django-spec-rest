# Views

Each view takes a kernel spec on `spec`. See [Concepts](../concepts.md) for
what the edge reads from the request and how a refusal is answered.

## Mutation views

::: django_spec_rest.views.mutation.service_create_view.ServiceCreateView

::: django_spec_rest.views.mutation.service_update_view.ServiceUpdateView

::: django_spec_rest.views.mutation.service_delete_view.ServiceDeleteView

## Selector views

::: django_spec_rest.views.query.selector_list_view.SelectorListView

::: django_spec_rest.views.query.selector_retrieve_view.SelectorRetrieveView

## Mutation flow mixin

::: django_spec_rest.views.mutation.mutation_flow_mixin.MutationFlowMixin

## The write's target

::: django_spec_rest.views.mutation.utils.resolve_mutation_instance
