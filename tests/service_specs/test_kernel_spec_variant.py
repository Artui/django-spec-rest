"""``kernel_spec_variant`` over a kernel spec: the per-request ``partial``, derived once.

A kernel spec is dispatched as declared, so the one variant a request of the
DRF edge still asks of it is a ``PATCH``'s: the spec with ``partial`` set,
built through the kernel's own ``derive`` and relaxed by the kernel's
``relax_partial`` when it is dispatched. Every other variant the drfs path
compiles is a seat a kernel spec declares itself, and asking for one is
refused. Each test reads the function through its public signature.
"""

from __future__ import annotations

import gc
from dataclasses import dataclass
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import (
    DataclassValidator,
    Grant,
    InvalidArguments,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
    dispatch,
    relax_partial,
)
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest.service_specs import kernel_spec_variant as module
from django_spec_rest.service_specs.kernel_spec_variant import kernel_spec_variant
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.views.test_kernel_views import _CreateView

_OPEN = (Unrestricted(),)


class _Note(serializers.Serializer):
    title = serializers.CharField()
    body = serializers.CharField()


def _seen(*, data: Any) -> dict[str, Any]:
    return dict(data)


def _spec(**fields: Any) -> ServiceSpec:
    fields.setdefault("validator", SerializerValidator(_Note))
    return ServiceSpec(service=_seen, permissions=_OPEN, atomic=False, **fields)


def test_the_default_variant_is_the_spec_itself() -> None:
    spec = _spec()

    assert kernel_spec_variant(spec) is spec


def test_a_partial_variant_is_derived_and_the_spec_is_untouched() -> None:
    spec = _spec()

    variant = kernel_spec_variant(spec, partial=True)

    assert isinstance(variant, ServiceSpec)
    assert variant is not spec
    assert variant.partial is True
    assert spec.partial is False
    assert variant.validator is spec.validator


def test_the_kernel_relaxes_the_variant_s_validator_parameters() -> None:
    """``relax_partial`` reads the derived flag, so every field is optional on the variant alone."""
    spec = _spec()
    variant = kernel_spec_variant(spec, partial=True)

    assert {p.name: p.required for p in relax_partial(variant, variant.parameters())} == {
        "title": False,
        "body": False,
    }
    assert {p.name: p.required for p in relax_partial(spec, spec.parameters())} == {
        "title": True,
        "body": True,
    }


@pytest.mark.django_db
def test_a_partial_variant_takes_a_call_the_spec_refuses() -> None:
    """The serializer validates partially too: what was sent, and nothing it left out."""
    spec = _spec()
    principal = AnonymousUser()

    with pytest.raises(InvalidArguments):
        dispatch(spec, principal=principal, arguments={"title": "t"})
    result = dispatch(
        kernel_spec_variant(spec, partial=True), principal=principal, arguments={"title": "t"}
    )

    assert result.value == {"title": "t"}


def test_a_whole_variant_of_a_partial_spec_is_derived_too() -> None:
    """A ``PUT`` against a spec declared partial asks for every field again."""
    spec = _spec(partial=True)

    variant = kernel_spec_variant(spec, partial=False)

    assert isinstance(variant, ServiceSpec)
    assert variant.partial is False


def test_each_variant_is_derived_once_per_source() -> None:
    """Held by identity, so a ``Grant`` minted for a variant covers it on the next call."""
    spec = _spec()
    twin = _spec(validator=spec.validator)

    first = kernel_spec_variant(spec, partial=True)

    assert kernel_spec_variant(spec, partial=True) is first
    # Equal declarations are two sources: a Grant binds the spec by identity.
    assert kernel_spec_variant(twin, partial=True) is not first


@pytest.mark.django_db
def test_a_grant_for_a_variant_covers_the_next_request_s_variant() -> None:
    spec = _spec()
    principal = AnonymousUser()
    grant = Grant(kernel_spec_variant(spec, partial=True), principal)

    result = dispatch(
        kernel_spec_variant(spec, partial=True),
        principal=principal,
        arguments={"body": "b"},
        grant=grant,
    )

    assert result.value == {"body": "b"}


def test_a_source_s_variants_go_with_it() -> None:
    spec = _spec()
    kernel_spec_variant(spec, partial=True)
    source_id = id(spec)
    assert source_id in module._VARIANTS

    del spec
    gc.collect()

    assert source_id not in module._VARIANTS


@pytest.mark.parametrize(
    ("spec", "partial"),
    [
        (_spec(), False),
        (_spec(partial=True), True),
        (_spec(validator=None), True),
        (SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=_OPEN), True),
    ],
    ids=["already-whole", "already-partial", "no-validator", "selector"],
)
def test_a_variant_with_nothing_to_change_is_the_spec_itself(spec: Any, partial: bool) -> None:
    """Returned as it is and held by nothing, so no source is kept alive by its own variant.

    A spec with no Validator has nothing a partial call may leave out, and the
    kernel refuses ``partial=True`` on one, so a ``PATCH`` runs it whole, as
    drfs compiles a spec with no ``input_serializer``. A selector spec has no
    ``partial``.
    """
    assert kernel_spec_variant(spec, partial=partial) is spec
    assert id(spec) not in module._VARIANTS


@dataclass
class _Plain:
    title: str


@pytest.mark.parametrize(
    "validator",
    [DataclassValidator(_Plain), SerializerValidator(_Plain)],
    ids=["dataclass-validator", "serializer-over-a-dataclass"],
)
def test_a_partial_variant_over_a_validator_that_cannot_be_partial_is_refused(
    validator: Any,
) -> None:
    """The kernel's own refusal, at ``derive``: such a Validator builds every field."""
    with pytest.raises(ImproperlyConfigured, match="cannot validate a partial call"):
        kernel_spec_variant(_spec(validator=validator), partial=True)


@pytest.mark.parametrize(
    "keyword",
    [
        {"unguarded": True},
        {"target": True},
        {"server_input": False},
        {"spread": True},
        {"lenient": True},
        {"excluded": frozenset({"user"})},
    ],
    ids=["unguarded", "target", "server-input", "spread", "lenient", "excluded"],
)
def test_a_drfs_only_variant_of_a_kernel_spec_is_refused(keyword: dict[str, Any]) -> None:
    """Each is a seat a kernel spec declares itself: its ``permissions``, its
    ``instance_selector_spec``, its providers, its Validator. Refused with or
    without ``partial`` beside it, rather than ignored."""
    spec = _spec()

    with pytest.raises(TypeError, match="declares the rest on itself"):
        kernel_spec_variant(spec, **keyword)
    with pytest.raises(TypeError, match="declares the rest on itself"):
        kernel_spec_variant(spec, partial=True, **keyword)


class _Flag(serializers.Serializer):
    published = serializers.BooleanField()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("lenient", "status"), [(False, 400), (True, 204)], ids=["typed", "lenient"]
)
def test_lenient_is_the_seat_s_word_over_a_live_view(lenient: bool, status: int) -> None:
    """A JSON ``"true"`` for a boolean is the kernel's refusal unless the spec's
    Validator says ``lenient``.

    The edge dispatches no lenient variant of a kernel spec: one spec answers
    one way on every transport, as the kernel's typed check does. An author
    who wants DRF's own coercion over HTTP declares it on the seat,
    ``SerializerValidator(lenient=True)``, and then every transport hands the
    serializer the value as sent.
    """
    seen: dict[str, Any] = {}

    def service(*, data: Any) -> None:
        seen.update(data)

    spec = ServiceSpec(
        service=service,
        permissions=_OPEN,
        validator=SerializerValidator(_Flag, lenient=lenient),
        atomic=False,
    )
    view = type("_View", (_CreateView,), {"spec": spec}).as_view()

    response = view(APIRequestFactory().post("/", {"published": "true"}, format="json"))

    assert response.status_code == status, response.data
    assert seen == ({"published": True} if lenient else {})
