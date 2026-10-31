"""``FieldMarking``, django-service-specs' own, plus the ``MARKING`` style key.

The key is exported from the same module as the class it labels because the two
are meaningless apart: ``MARKING`` exists only to carry a ``FieldMarking``, and a
``FieldMarking`` is only ever found under it.

The class is the kernel's, re-exported at this path. The key is this package's,
because a serializer field's ``style`` bag is where a DRF declaration puts a
marking, and the kernel reads a marking off its own Output instead.
"""

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
