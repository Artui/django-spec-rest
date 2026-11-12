from __future__ import annotations


class GetQuerysetScopeWarning(UserWarning):
    """A viewset overrides ``get_queryset()``, which scopes none of the rows its specs serve.

    A ``UserWarning``, because Python hides a ``DeprecationWarning`` outside
    ``__main__`` and the failure this reports is silent otherwise. Its text
    begins with the stable id ``django_spec_rest.W001``.
    """
