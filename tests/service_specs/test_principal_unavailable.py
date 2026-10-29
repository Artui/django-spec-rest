"""Tests for the dual-base ``PrincipalUnavailable``: the kernel's refusal of a principal, answered 403.

As for ``NotPermitted``: the codes, the ``ErrorDetail`` type and the kernel's
``message`` are asserted, because a response body is identical for a class
whose bases are in the wrong order.
"""

from __future__ import annotations

import pytest
from django_service_specs.authorization.principal_unavailable import (
    PrincipalUnavailable as KernelPrincipalUnavailable,
)
from django_service_specs.services.service_error import ServiceError as KernelServiceError
from django_service_specs.types.dispatch_error import DispatchError
from rest_framework.exceptions import ErrorDetail, PermissionDenied

from django_spec_rest.exceptions.service_error import ServiceError
from django_spec_rest.service_specs.principal_unavailable import PrincipalUnavailable
from tests.service_specs.served_status import served_status


class TestItIsBothClasses:
    def test_it_is_the_kernels_refusal_and_drfs_denial(self) -> None:
        assert issubclass(PrincipalUnavailable, KernelPrincipalUnavailable)
        assert issubclass(PrincipalUnavailable, DispatchError)
        assert issubclass(PrincipalUnavailable, PermissionDenied)

    @pytest.mark.parametrize("service_error", [KernelServiceError, ServiceError])
    def test_it_is_never_a_service_error(self, service_error: type[Exception]) -> None:
        assert not issubclass(PrincipalUnavailable, service_error)


class TestBothInitsRan:
    def test_the_default_is_the_kernels_message_not_drfs(self) -> None:
        # DRF's default reads as a permission refusal; this one says there is
        # nobody to refuse, and the kernel's wording is the one kept.
        exc = PrincipalUnavailable()
        assert exc.message == KernelPrincipalUnavailable.default_message
        assert exc.detail == KernelPrincipalUnavailable.default_message
        assert exc.detail != PermissionDenied.default_detail

    def test_a_message_is_both_the_kernels_message_and_drfs_detail(self) -> None:
        exc = PrincipalUnavailable("That account is deactivated.")
        assert exc.message == "That account is deactivated."
        assert isinstance(exc.detail, ErrorDetail)
        assert exc.detail == "That account is deactivated."

    def test_get_codes_is_drfs_denial_code(self) -> None:
        assert PrincipalUnavailable().get_codes() == "permission_denied"

    def test_a_code_given_is_kept(self) -> None:
        assert PrincipalUnavailable(code="deactivated").get_codes() == "deactivated"


class TestDrfAnswersIt:
    def test_drf_answers_it_403(self) -> None:
        assert served_status(PrincipalUnavailable()) == 403

    def test_the_kernels_class_alone_is_a_500(self) -> None:
        assert served_status(KernelPrincipalUnavailable()) == 500


class TestFromKernel:
    def test_a_kernel_refusal_keeps_its_message_as_message_and_detail(self) -> None:
        twin = PrincipalUnavailable.from_kernel(KernelPrincipalUnavailable("Gone."))
        assert type(twin) is PrincipalUnavailable
        assert twin.message == "Gone."
        assert str(twin.detail) == "Gone."
        assert twin.get_codes() == "permission_denied"

    def test_the_kernel_s_default_message_is_carried(self) -> None:
        kernel = KernelPrincipalUnavailable()
        assert PrincipalUnavailable.from_kernel(kernel).message == kernel.message
