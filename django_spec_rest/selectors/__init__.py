"""Selector protocols — typed shapes for query callables.

See ``django_spec_rest.services`` for the extras-typing
conventions; selectors follow the identical pattern.
"""

from django_spec_rest.selectors.acall_selector import acall_selector
from django_spec_rest.selectors.async_selector import AsyncSelector
from django_spec_rest.selectors.call_selector import call_selector
from django_spec_rest.selectors.list_selector import ListSelector
from django_spec_rest.selectors.retrieve_selector import RetrieveSelector
from django_spec_rest.selectors.selector import Selector
from django_spec_rest.selectors.utils import (
    amaterialize_retrieve,
    apply_queryset_shaping,
    arun_selector,
    is_queryset,
    materialize_retrieve,
    run_selector,
)

__all__ = [
    "AsyncSelector",
    "ListSelector",
    "RetrieveSelector",
    "Selector",
    "acall_selector",
    "amaterialize_retrieve",
    "apply_queryset_shaping",
    "arun_selector",
    "call_selector",
    "is_queryset",
    "materialize_retrieve",
    "run_selector",
]
