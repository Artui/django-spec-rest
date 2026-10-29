"""Query views — ``List`` and ``Retrieve`` backed by selector callables."""

from django_spec_rest.views.query.selector_list_view import SelectorListView
from django_spec_rest.views.query.selector_retrieve_view import (
    SelectorRetrieveView,
)

__all__ = [
    "SelectorListView",
    "SelectorRetrieveView",
]
