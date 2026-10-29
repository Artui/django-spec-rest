"""Mutation helpers — DRF-style attribute application with change tracking.

These functions are the core value-add of the library. Services call them
explicitly inside their own bodies; the library never calls them implicitly.

Result types (``ChangeResult``, ``FieldChange``, ``UNSET``) live in
``django_spec_rest.types`` and are re-exported from the top-level
package for convenience.
"""

from django_spec_rest.mutations.acreate_from_input import acreate_from_input
from django_spec_rest.mutations.apply_input import apply_input
from django_spec_rest.mutations.aupdate_from_input import aupdate_from_input
from django_spec_rest.mutations.create_from_input import create_from_input
from django_spec_rest.mutations.update_from_input import update_from_input

__all__ = [
    "acreate_from_input",
    "apply_input",
    "aupdate_from_input",
    "create_from_input",
    "update_from_input",
]
