"""Base view classes.

The mutation views (``ServiceCreateView``, ``ServiceUpdateView``,
``ServiceDeleteView``) and query views (``SelectorListView``,
``SelectorRetrieveView``) are re-exported here for convenience.
"""

from django_spec_rest.views.mutation import (
    ServiceCreateView,
    ServiceDeleteView,
    ServiceUpdateView,
)
from django_spec_rest.views.query import (
    SelectorListView,
    SelectorRetrieveView,
)

__all__ = [
    "SelectorListView",
    "SelectorRetrieveView",
    "ServiceCreateView",
    "ServiceDeleteView",
    "ServiceUpdateView",
]
