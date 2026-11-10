from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs.mutations.create_from_input import create_from_input
from django_service_specs.mutations.register_row_error import register_row_error
from django_service_specs.parameters.invalid_arguments import (
    InvalidArguments as KernelInvalidArguments,
)
from django_service_specs.relations.child_spec import ChildSpec
from rest_framework.exceptions import ErrorDetail, ValidationError

from django_spec_rest.service_specs.drf_invalid_arguments import DRFInvalidArguments
from django_spec_rest.service_specs.register_drf_row_errors import (
    register_drf_row_errors,
)
from tests.testapp.models import Catalog, Section

_ROWS: dict[str, Any] = {"name": "c", "sections": [{"title": "ok"}, {"title": "bad"}]}


def _sections_refusing(error: Exception) -> dict[str, ChildSpec]:
    """Sections written by a row service that refuses the row titled ``bad`` with ``error``."""

    def create(*, data: dict[str, Any]) -> Section:
        if data["title"] == "bad":
            raise error
        return Section.objects.create(**data)

    return {"sections": ChildSpec(model=Section, fk="catalog", create_service=create)}


@pytest.mark.django_db
class TestARowsDrfRefusal:
    def test_it_lands_at_its_row_and_keeps_its_class_and_codes(self) -> None:
        register_drf_row_errors()
        with pytest.raises(ValidationError) as excinfo:
            create_from_input(
                Catalog,
                _ROWS,
                relations=_sections_refusing(ValidationError({"title": ["No."]}, code="rude")),
            )
        assert type(excinfo.value) is ValidationError
        assert excinfo.value.detail == {"sections": {1: {"title": ["No."]}}}
        assert isinstance(excinfo.value.detail["sections"][1]["title"][0], ErrorDetail)
        assert excinfo.value.get_codes() == {"sections": {1: {"title": ["rude"]}}}

    def test_a_message_about_the_row_itself_lands_under_non_field_errors(self) -> None:
        register_drf_row_errors()
        with pytest.raises(ValidationError) as excinfo:
            create_from_input(
                Catalog, _ROWS, relations=_sections_refusing(ValidationError("Bad row."))
            )
        assert excinfo.value.get_codes() == {"sections": {1: {"non_field_errors": ["invalid"]}}}

    def test_the_dual_class_leaves_a_row_as_the_kernels_class(self) -> None:
        # The kernel's own ``DRFInvalidArguments`` is read before any registered class.
        register_drf_row_errors()
        with pytest.raises(KernelInvalidArguments) as excinfo:
            create_from_input(
                Catalog,
                _ROWS,
                relations=_sections_refusing(DRFInvalidArguments({"title": ["No."]})),
            )
        assert type(excinfo.value) is KernelInvalidArguments
        assert excinfo.value.detail == {"sections": {1: {"title": ["No."]}}}


class TestTheRegistration:
    def test_it_may_run_twice(self) -> None:
        register_drf_row_errors()
        register_drf_row_errors()

    def test_it_registered_drf_s_validation_error_with_its_own_reader(self) -> None:
        # The kernel refuses a second reader for a registered class.
        register_drf_row_errors()
        with pytest.raises(ImproperlyConfigured, match="already registered"):
            register_row_error(ValidationError, lambda exc: exc.detail)
