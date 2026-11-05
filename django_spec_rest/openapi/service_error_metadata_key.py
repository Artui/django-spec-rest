"""The spec ``metadata`` key that declares an operation can answer a plain ``ServiceError``."""

from __future__ import annotations

SERVICE_ERROR_METADATA_KEY = "document_service_error"
"""``metadata={"document_service_error": True}`` documents the ``422`` on that spec's operations.

The edge answers a plain ``ServiceError`` 422, from the service, the selector,
a precondition or a provider; the schema cannot tell which specs raise one, so
it documents the 422 only where a spec says so. Read by
``ServiceAutoSchema.documents_service_error`` off the spec the route serves,
never off a nested target or re-read spec. The name is drfs' own
``document_service_error``, so a drfs spec carrying ``document_service_error=True``
moves by putting the flag in its ``metadata``. The value is ``True`` or
``False``; any other is refused when the schema is generated.
"""
