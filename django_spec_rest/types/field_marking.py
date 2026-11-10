from __future__ import annotations

from typing import Final

from django_service_specs.output.field_marking import FieldMarking

MARKING: Final = "drf_marking"
"""Key under which an :class:`FieldMarking` is declared in a DRF field's ``style``.

Namespaced rather than bare (``"agent"``) because ``style`` is a shared bag any
library may write to. The namespacing is courtesy, not correctness: readers
match on the *value* being an ``FieldMarking``, so a marking under another key
still takes effect and another library's data under ``MARKING`` is refused loudly
rather than silently misread.
"""

__all__ = ["MARKING", "FieldMarking"]
