"""``run_service`` is django-service-specs' own; its behaviour is tested there."""

from __future__ import annotations

from django_service_specs.services.run_service import run_service as kernel_run_service

import django_spec_rest
from django_spec_rest.services.run_service import run_service


def test_is_the_kernel_s_object_at_drfs_path_and_root() -> None:
    assert run_service is kernel_run_service
    assert django_spec_rest.run_service is kernel_run_service
