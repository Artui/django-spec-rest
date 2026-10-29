"""Mutation views — ``Create``, ``Update``, ``Delete`` backed by services."""

from django_spec_rest.views.mutation.service_create_view import ServiceCreateView
from django_spec_rest.views.mutation.service_delete_view import ServiceDeleteView
from django_spec_rest.views.mutation.service_update_view import ServiceUpdateView

__all__ = [
    "ServiceCreateView",
    "ServiceDeleteView",
    "ServiceUpdateView",
]
