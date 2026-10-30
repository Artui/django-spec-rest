"""A serializer refusing to render leaves the presenter as the kernel's ``InvalidArguments``.

The kernel's ``present`` and ``present_for_audience`` call the presenter, and
a kernel route reads the kernel's refusal of the arguments, never DRF's
``ValidationError``. So ``SerializerPresenter.presented`` answers a
serializer's refusal as the dual ``DRFInvalidArguments``, still DRF's class:

- a mapping detail passes as it is;
- a list detail, which is all DRF makes of a message, goes under the
  kernel's non-field key;
- each message keeps its code.

A view serving a kernel spec presents through the kernel's ``present``, so the
refusal reaches HTTP as the dual class, a ``400`` whose body is the mapping.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django_service_specs import SelectorKind, SelectorSpec, ServiceSpec, Unrestricted
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.apresent import apresent
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.present import present
from django_service_specs.parameters.invalid_arguments import (
    InvalidArguments as KernelInvalidArguments,
)
from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory

from django_spec_rest import SelectorRetrieveView, ServiceCreateView
from django_spec_rest.service_specs.drf_invalid_arguments import DRFInvalidArguments
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Post

pytestmark = pytest.mark.django_db

_OPEN = (Unrestricted(),)


def _refusing(error: Exception) -> type[serializers.Serializer]:
    class _Refusing(serializers.Serializer):
        title = serializers.CharField()

        def to_representation(self, instance: Any) -> Any:
            raise error

    return _Refusing


_DETAILS = pytest.mark.parametrize(
    ("error", "detail", "codes"),
    [
        (
            ValidationError({"fields": ["No such field: nope."]}, code="unknown_field"),
            {"fields": ["No such field: nope."]},
            {"fields": ["unknown_field"]},
        ),
        (
            ValidationError(["Cannot render."], code="unrenderable"),
            {NON_FIELD_ERRORS: ["Cannot render."]},
            {NON_FIELD_ERRORS: ["unrenderable"]},
        ),
        (
            ValidationError("Cannot render."),
            {NON_FIELD_ERRORS: ["Cannot render."]},
            {NON_FIELD_ERRORS: ["invalid"]},
        ),
    ],
    ids=["mapping", "list", "message"],
)


def _retrieve(error: Exception) -> SelectorSpec:
    post = Post.objects.create(title="t")
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda: Post.objects.get(pk=post.pk),
        permissions=_OPEN,
        presenter=SerializerPresenter(_refusing(error)),
    )


@_DETAILS
def test_present_refuses_as_the_kernel_s_invalid_arguments(
    error: ValidationError, detail: Any, codes: Any
) -> None:
    with pytest.raises(KernelInvalidArguments) as excinfo:
        SerializerPresenter(_refusing(error)).present(object())

    refusal = excinfo.value
    assert isinstance(refusal, ValidationError)
    assert refusal.detail == detail
    assert refusal.get_codes() == codes
    assert refusal.__cause__ is error


@_DETAILS
def test_the_kernel_s_present_refuses_as_the_kernel_s_invalid_arguments(
    error: ValidationError, detail: Any, codes: Any
) -> None:
    """``present`` hands the presenter the call's context: the other half of ``presented``."""
    spec = _retrieve(error)
    result = dispatch(spec, principal=AnonymousUser(), arguments={})

    with pytest.raises(KernelInvalidArguments) as excinfo:
        present(spec, result)

    assert excinfo.value.detail == detail
    assert excinfo.value.get_codes() == codes  # ty: ignore[unresolved-attribute]


@pytest.mark.django_db(transaction=True)
async def test_the_kernel_s_apresent_refuses_as_the_kernel_s_invalid_arguments() -> None:
    """Off the loop too: the refusal crosses ``apresent``'s thread hop as raised."""
    post = await Post.objects.acreate(title="t")
    spec = SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda: Post.objects.get(pk=post.pk),
        permissions=_OPEN,
        presenter=SerializerPresenter(_refusing(ValidationError("Cannot render."))),
    )
    result = await adispatch(spec, principal=AnonymousUser(), arguments={})

    with pytest.raises(DRFInvalidArguments) as excinfo:
        await apresent(spec, result)

    assert excinfo.value.detail == {NON_FIELD_ERRORS: ["Cannot render."]}


def test_the_kernel_s_own_refusal_leaves_exactly_as_raised() -> None:
    """A serializer raising the kernel's class, the dual one here, is not rebuilt."""
    error = DRFInvalidArguments({"fields": ["kept"]})

    with pytest.raises(DRFInvalidArguments) as excinfo:
        SerializerPresenter(_refusing(error)).present(object())

    assert excinfo.value is error


def test_any_other_exception_leaves_exactly_as_raised() -> None:
    error = LookupError("not a refusal")

    with pytest.raises(LookupError) as excinfo:
        SerializerPresenter(_refusing(error)).present(object())

    assert excinfo.value is error


class _CreateView(ServiceCreateView):
    """A create view over a kernel spec, whose answer the spec's presenter renders.

    ``get_permissions`` answers the view's own classes, as the spine's views do:
    ``MutationFlowMixin``'s reads a drfs-only spec field."""

    permission_classes: Any = []

    def get_permissions(self) -> list[Any]:
        return [permission() for permission in self.permission_classes]


@pytest.mark.parametrize(
    ("error", "body"),
    [
        # Changed by design: drfs answered a message as DRF's bare list,
        # ``["Cannot render."]``. A kernel spec presents through the kernel's
        # ``present``, where the refusal is the dual class with the message
        # under the kernel's non-field key, and that mapping is the body.
        (ValidationError("Cannot render."), b'{"non_field_errors":["Cannot render."]}'),
        (ValidationError({"fields": ["nope"]}), b'{"fields":["nope"]}'),
    ],
    ids=["message", "mapping"],
)
def test_a_live_view_answers_the_refusal_as_a_400(error: ValidationError, body: bytes) -> None:
    spec = ServiceSpec(
        service=lambda: Post.objects.create(title="t"),
        permissions=_OPEN,
        presenter=SerializerPresenter(_refusing(error)),
    )
    view = type("_View", (_CreateView,), {"spec": spec}).as_view()

    response = view(APIRequestFactory().post("/", {}, format="json"))
    response.render()

    assert (response.status_code, response.content) == (400, body)


def test_a_retrieve_view_answers_the_refusal_as_a_400() -> None:
    """A retrieve view presents a kernel spec through the spec's presenter, so the
    refusal is the dual class and the body is its mapping, as on a create view."""
    spec = _retrieve(ValidationError({"fields": ["nope"]}))

    class _View(SelectorRetrieveView):
        permission_classes: Any = []

        def get_permissions(self) -> list[Any]:
            return []

    _View.spec = spec
    response = _View.as_view()(APIRequestFactory().get("/"))
    response.render()

    assert (response.status_code, response.content) == (400, b'{"fields":["nope"]}')
