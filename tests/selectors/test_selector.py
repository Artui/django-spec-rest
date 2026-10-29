"""``Selector`` and ``AsyncSelector`` are django-service-specs' own Protocols."""

from __future__ import annotations

from django_service_specs.selectors.async_selector import AsyncSelector as KernelAsyncSelector
from django_service_specs.selectors.selector import Selector as KernelSelector

import django_spec_rest
from django_spec_rest.selectors.async_selector import AsyncSelector
from django_spec_rest.selectors.selector import Selector


def test_selector_is_the_kernel_s_protocol() -> None:
    assert Selector is KernelSelector
    assert django_spec_rest.Selector is KernelSelector


def test_async_selector_is_the_kernel_s_protocol() -> None:
    assert AsyncSelector is KernelAsyncSelector
    assert django_spec_rest.AsyncSelector is KernelAsyncSelector
