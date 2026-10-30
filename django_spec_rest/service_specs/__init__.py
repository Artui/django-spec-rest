"""The DRF adapter over ``django-service-specs``.

This subpackage imports DRF by design: it is where a serializer becomes a
validator and a presenter, DRF's permission classes become a permission check,
and a refusal crosses between the kernel's errors and DRF's exceptions.
"""

from __future__ import annotations
