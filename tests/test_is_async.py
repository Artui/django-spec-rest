"""``is_async`` is django-service-specs' own; its behaviour is tested there."""

from __future__ import annotations

from django_service_specs.types.is_async import is_async as kernel_is_async

import django_spec_rest
from django_spec_rest.is_async import is_async


def test_is_the_kernel_s_object_at_drfs_path_and_root() -> None:
    assert is_async is kernel_is_async
    assert django_spec_rest.is_async is kernel_is_async
