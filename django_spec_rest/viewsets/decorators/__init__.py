"""Viewset decorators."""

from django_spec_rest.viewsets.decorators.selector_action import selector_action
from django_spec_rest.viewsets.decorators.service_action import service_action

__all__ = [
    "selector_action",
    "service_action",
]
