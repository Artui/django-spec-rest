from __future__ import annotations


class GetQuerysetScopeWarning(UserWarning):
    """A viewset overrides ``get_queryset()``, which scopes none of the rows its specs serve."""
