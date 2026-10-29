"""Audience projection — one serializer, more than one kind of reader.

A serializer written for a frontend is read verbatim by a model when the same
spec is exposed as an agent tool, and the two want different subsets of it.
These helpers let the difference be declared once, on the field, and applied by
every agent transport identically. The DRF view path reads none of it.
"""

from django_spec_rest.audience.annotate_output_schema import annotate_output_schema
from django_spec_rest.audience.audience_projection_for_spec import (
    audience_projection_for_spec,
)
from django_spec_rest.audience.build_audience_projection import build_audience_projection
from django_spec_rest.audience.project_payload import project_payload

__all__ = [
    "audience_projection_for_spec",
    "annotate_output_schema",
    "build_audience_projection",
    "project_payload",
]
