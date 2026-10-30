"""``kernel_spec_variant`` over a kernel spec: the per-request ``partial`` and ``lenient``, derived once.

A kernel spec is dispatched as declared, so the variants a request of the DRF
edge may still ask of it are two: a ``PATCH``'s, the spec with ``partial``
set and relaxed by the kernel's ``relax_partial`` when it is dispatched, and a
lenient one, its ``SerializerValidator`` declared ``lenient`` so DRF's own
coercion answers. Both are built through the kernel's own ``derive``. Every
other variant the drfs path compiles is a seat a kernel spec declares itself,
and asking for one is refused. Each test reads the function through its
public signature.
"""

from __future__ import annotations

import gc
from dataclasses import dataclass
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
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
from django_spec_rest.types.json_schema_registry import JsonSchemaRegistry
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


@dataclass
class _Plain:
    title: str


@pytest.mark.parametrize(
    ("spec", "keywords"),
    [
        (_spec(), {"partial": False}),
        (_spec(partial=True), {"partial": True}),
        (_spec(validator=None), {"partial": True}),
        (_spec(validator=SerializerValidator(_Note, lenient=True)), {"lenient": True}),
        (_spec(validator=DataclassValidator(_Plain)), {"lenient": True}),
        (
            SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=_OPEN),
            {"partial": True, "lenient": True},
        ),
    ],
    ids=[
        "already-whole",
        "already-partial",
        "no-validator",
        "already-lenient",
        "lenient-over-another-validator",
        "selector",
    ],
)
def test_a_variant_with_nothing_to_change_is_the_spec_itself(
    spec: Any, keywords: dict[str, Any]
) -> None:
    """Returned as it is and held by nothing, so no source is kept alive by its own variant.

    A spec with no Validator has nothing a partial call may leave out, and the
    kernel refuses ``partial=True`` on one, so a ``PATCH`` runs it whole, as
    drfs compiles a spec with no ``input_serializer``. A Validator other than
    a ``SerializerValidator`` declares what it takes as it validates it, so
    ``lenient`` has nothing to relax. A selector spec has neither.
    """
    assert kernel_spec_variant(spec, **keywords) is spec
    assert id(spec) not in module._VARIANTS


@pytest.mark.parametrize(
    "validator",
    [DataclassValidator(_Plain), SerializerValidator(_Plain)],
    ids=["dataclass-validator", "serializer-over-a-dataclass"],
)
def test_a_partial_variant_over_a_validator_that_cannot_be_partial_is_the_spec_itself(
    validator: Any,
) -> None:
    """Validated whole, as drfs answered: a ``PATCH`` to a dataclass is not partial.

    Such a Validator builds every field, so the kernel refuses ``partial=True``
    at ``derive``; the variant is the spec instead, and held by nothing.
    """
    spec = _spec(validator=validator)

    assert kernel_spec_variant(spec, partial=True) is spec
    assert id(spec) not in module._VARIANTS


@pytest.mark.parametrize(
    "keyword",
    [
        {"unguarded": True},
        {"target": True},
        {"server_input": False},
        {"spread": True},
        {"excluded": frozenset({"user"})},
    ],
    ids=["unguarded", "target", "server-input", "spread", "excluded"],
)
def test_a_drfs_only_variant_of_a_kernel_spec_is_refused(keyword: dict[str, Any]) -> None:
    """Each is a seat a kernel spec declares itself: its ``permissions``, its
    ``instance_selector_spec``, its providers, its Validator's ``excluded``.
    Refused with or without a kernel variant beside it, rather than ignored."""
    spec = _spec()

    with pytest.raises(TypeError, match="declares the rest on itself"):
        kernel_spec_variant(spec, **keyword)
    with pytest.raises(TypeError, match="declares the rest on itself"):
        kernel_spec_variant(spec, partial=True, lenient=True, **keyword)


class _Flag(serializers.Serializer):
    published = serializers.BooleanField()


def _flagged(**validator: Any) -> ServiceSpec:
    return _spec(validator=SerializerValidator(_Flag, **validator))


@pytest.mark.django_db
def test_a_lenient_variant_takes_what_drf_coerces() -> None:
    """A typed ``"true"`` for a boolean is the kernel's refusal on the spec and DRF's ``True`` on the variant."""
    spec = _flagged()
    principal = AnonymousUser()

    with pytest.raises(InvalidArguments) as excinfo:
        dispatch(spec, principal=principal, arguments={"published": "true"})
    assert [str(message) for message in excinfo.value.detail["published"]] == [
        "Expected a boolean."
    ]
    result = dispatch(
        kernel_spec_variant(spec, lenient=True),
        principal=principal,
        arguments={"published": "true"},
    )

    assert result.value == {"published": True}


def test_a_lenient_variant_carries_the_validator_s_other_keywords() -> None:
    def context() -> dict[str, Any]:
        return {}

    registry = JsonSchemaRegistry()
    spec = _flagged(
        serializer_context=context,
        excluded=frozenset({"user"}),
        server_owned=frozenset({"published"}),
        json_schema_registry=registry,
    )

    variant = kernel_spec_variant(spec, lenient=True)

    assert isinstance(variant, ServiceSpec)
    validator = variant.validator
    assert isinstance(validator, SerializerValidator)
    assert validator.lenient is True
    assert validator.serializer is _Flag
    assert validator.serializer_context is context
    assert validator.excluded == frozenset({"user"})
    assert validator.server_owned == frozenset({"published"})
    assert validator.json_schema_registry is registry


@pytest.mark.parametrize(("low", "high"), [(None, None), (1, 3)], ids=["undeclared", "declared"])
def test_a_lenient_variant_keeps_a_many_spec_s_bounds(low: int | None, high: int | None) -> None:
    """A kernel spec declares its list's bounds, so the kernel's cap stays where the author left it."""
    spec = _spec(many=True, many_min_length=low, many_max_length=high)

    variant = kernel_spec_variant(spec, lenient=True)

    assert isinstance(variant, ServiceSpec)
    assert variant is not spec
    assert (variant.many_min_length, variant.many_max_length) == (low, high)


def test_partial_and_lenient_derive_one_variant_together() -> None:
    spec = _spec()

    both = kernel_spec_variant(spec, partial=True, lenient=True)

    assert isinstance(both, ServiceSpec)
    assert both.partial is True
    assert isinstance(both.validator, SerializerValidator)
    assert both.validator.lenient is True
    assert both is not kernel_spec_variant(spec, partial=True)
    assert both is not kernel_spec_variant(spec, lenient=True)
    assert kernel_spec_variant(spec, partial=True, lenient=True) is both


# drfs chose ``lenient`` per request: ``over_http(view)`` (dispatch/utils.py) was true for any
# call a live view dispatched, so every request through a DRF view validated by its serializer
# alone, whatever the spec's own Validator declared. The kernel route keeps that for a form
# body, whose values are strings DRF's fields parse, and keeps the kernel's typed check for a
# JSON body, whose client typed its values.


def _flag_view(lenient: bool) -> tuple[Any, dict[str, Any]]:
    seen: dict[str, Any] = {}

    def service(*, data: Any) -> None:
        seen.update(data)

    spec = ServiceSpec(
        service=service,
        permissions=_OPEN,
        validator=SerializerValidator(_Flag, lenient=lenient),
        atomic=False,
    )
    return type("_View", (_CreateView,), {"spec": spec}).as_view(), seen


@pytest.mark.django_db
@pytest.mark.parametrize("fmt", ["multipart", None], ids=["multipart", "urlencoded"])
def test_a_live_view_validates_a_form_body_by_its_serializer_alone(fmt: str | None) -> None:
    """A checkbox's ``"on"`` is a 204 with ``published=True``, as drfs answered,
    though the spec's Validator is not declared lenient."""
    view, seen = _flag_view(lenient=False)
    factory = APIRequestFactory()
    request = (
        factory.post("/", {"published": "on"}, format=fmt)
        if fmt
        else factory.post("/", "published=on", content_type="application/x-www-form-urlencoded")
    )

    response = view(request)

    assert response.status_code == 204, response.data
    assert seen == {"published": True}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("lenient", "status"), [(False, 400), (True, 204)], ids=["undeclared", "declared"]
)
def test_a_json_body_meets_the_spec_s_own_validator(lenient: bool, status: int) -> None:
    """A JSON ``"true"`` for a boolean is the typed check's to refuse, unless the
    spec's own Validator is declared lenient, which takes it as DRF does."""
    view, seen = _flag_view(lenient=lenient)

    response = view(APIRequestFactory().post("/", {"published": "true"}, format="json"))

    assert response.status_code == status, response.data
    assert seen == ({"published": True} if lenient else {})
