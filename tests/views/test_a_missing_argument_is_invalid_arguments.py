"""A missing required argument is refused as ``DRFInvalidArguments``, never as a service's refusal.

The kernel refuses it, and the kernel route's refusal map leaves it as the
dual class: DRF's ``ValidationError`` and the kernel's ``InvalidArguments`` at
once, so an ``except`` written against either catches it. It is neither a
``ServiceValidationError`` nor a ``ServiceError``, since a business rule a
service states is a different refusal, and DRF answers it ``400`` keyed by the
argument.
"""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import (
    InvalidArguments as KernelInvalidArguments,
)
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceError,
    ServiceSpec,
    ServiceValidationError,
    Unrestricted,
)
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory

from django_spec_rest.dispatch.kernel_edge import dispatch_kernel_spec
from django_spec_rest.service_specs.drf_invalid_arguments import DRFInvalidArguments
from tests.views.test_kernel_edge import _parts
from tests.views.test_kernel_views import _CreateView

pytestmark = pytest.mark.django_db

_OPEN = (Unrestricted(),)


def _tag(*, tenant: str) -> dict[str, str]:
    return {"tenant": tenant}


def _unfilled(*, tenant: str) -> list[Any]:
    return []


def _any_instance(*, instance: Any) -> str:
    return "ran"


# Required: the mount check refuses an optional read over a keyword with no default, and a
# missing optional one would not be "missing" anyway.
_TENANT = Parameters.of(Parameter("tenant", "string", required=True))
_SERVICE = ServiceSpec(service=_tag, permissions=_OPEN, reads=_TENANT, atomic=False)
_SELECTOR = SelectorSpec(
    kind=SelectorKind.LIST, selector=_unfilled, permissions=_OPEN, reads=_TENANT
)
_TARGET_LOOKUP = ServiceSpec(
    service=_any_instance,
    permissions=_OPEN,
    instance_selector_spec=SelectorSpec(
        kind=SelectorKind.RETRIEVE, selector=_unfilled, permissions=_OPEN, reads=_TENANT
    ),
    atomic=False,
)
_SPECS = pytest.mark.parametrize(
    "spec", [_SERVICE, _SELECTOR, _TARGET_LOOKUP], ids=["service", "selector", "target-lookup"]
)


@_SPECS
def test_a_missing_argument_is_caught_as_drf_and_the_kernel_catch_it(spec: Any) -> None:
    for caught in (ValidationError, KernelInvalidArguments):
        with pytest.raises(caught) as raised:
            dispatch_kernel_spec(spec, **_parts({}))

        assert type(raised.value) is DRFInvalidArguments
        assert not isinstance(raised.value, ServiceValidationError | ServiceError)
        assert [str(error) for error in raised.value.detail["tenant"]] == [
            "This field is required."
        ]
        assert raised.value.get_codes() == {"tenant": ["required"]}


def test_a_view_answers_a_missing_argument_400_keyed_by_the_argument() -> None:
    view = type("_View", (_CreateView,), {"spec": _SERVICE}).as_view()
    response = view(APIRequestFactory().post("/", {}, format="json"))

    assert response.status_code == 400
    assert response.data == {"tenant": ["This field is required."]}
