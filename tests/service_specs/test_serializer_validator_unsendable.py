"""``SerializerValidator.unsendable``: the required fields no call can send.

A field named in ``RESERVED_POOL_SEEDS``, in ``BOUND`` or in ``excluded`` is no
parameter, so a call through the kernel's own ``dispatch`` has nowhere to put
its value, while the DRF edge reads it from the body. A transport reads the
attribute to refuse a spec whose call could never validate. Each spec here is
the kernel's own ``ServiceSpec`` with a ``SerializerValidator`` on its seat,
and each test reads the attribute off that seat.

The kernel's ``Validator`` does not declare the attribute yet, so a reader
holding any other Validator still reads it with ``getattr`` and a default.
The test of that default is a strict xfail until the kernel declares it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser, User
from django_service_specs import (
    Grant,
    InvalidArguments,
    Parameters,
    ServiceSpec,
    UnknownArguments,
    Unrestricted,
    ValidationContext,
    Validator,
    dispatch,
)
from rest_framework import serializers

from django_spec_rest.service_specs.serializer_validator import SerializerValidator

_OPEN = (Unrestricted(),)


class _RequiredUserIn(serializers.Serializer):
    title = serializers.CharField()
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())


class _RequiredSerializerIn(serializers.Serializer):
    title = serializers.CharField()
    serializer = serializers.CharField()


class _OptionalSeedNamesIn(serializers.Serializer):
    title = serializers.CharField()
    user = serializers.CharField(required=False)
    result = serializers.CharField(default="x")
    serializer = serializers.CharField(required=False, allow_null=True)


class _ReadOnlySeedNamesIn(serializers.Serializer):
    title = serializers.CharField()
    user = serializers.CharField(read_only=True)
    serializer = serializers.CharField(read_only=True)


class _RequiredResultIn(serializers.Serializer):
    title = serializers.CharField()
    result = serializers.CharField()


class _HiddenUserIn(serializers.Serializer):
    title = serializers.CharField()
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())


class _TenantIn(serializers.Serializer):
    title = serializers.CharField()
    tenant = serializers.CharField()


def _noop(**_: Any) -> None:
    return None


def _spec(serializer: type[Any], **fields: Any) -> ServiceSpec:
    return ServiceSpec(
        service=_noop,
        permissions=_OPEN,
        validator=SerializerValidator(serializer),
        atomic=False,
        **fields,
    )


def _validator_of(serializer: type[Any], **fields: Any) -> SerializerValidator:
    validator = _spec(serializer, **fields).validator
    assert isinstance(validator, SerializerValidator)
    return validator


@pytest.mark.django_db
def test_a_required_field_named_user_is_unsendable() -> None:
    validator = _validator_of(_RequiredUserIn)

    assert validator.parameters().names() == frozenset({"title"})
    assert validator.unsendable == frozenset({"user"})


def test_a_required_field_named_serializer_is_unsendable() -> None:
    """``serializer`` is in ``BOUND``, and the DRF edge serves it, so it is named like ``user``."""
    validator = _validator_of(_RequiredSerializerIn)

    assert validator.parameters().names() == frozenset({"title"})
    assert validator.unsendable == frozenset({"serializer"})


def test_an_optional_field_is_not_unsendable() -> None:
    """A call that leaves ``user``, ``result`` or ``serializer`` out validates, so none is named."""
    assert _validator_of(_OptionalSeedNamesIn).unsendable == frozenset()


def test_a_read_only_field_is_not_unsendable() -> None:
    assert _validator_of(_ReadOnlySeedNamesIn).unsendable == frozenset()


def test_a_field_named_like_no_seed_is_a_parameter_and_not_unsendable() -> None:
    """The Validator declares ``tenant``, so a call can send it."""
    validator = _validator_of(_TenantIn)

    assert validator.parameters().names() == frozenset({"title", "tenant"})
    assert validator.unsendable == frozenset()


def test_a_field_the_validator_excludes_is_unsendable_when_required() -> None:
    """The name ``excluded`` takes out of ``parameters()`` is the one ``unsendable`` names.

    Held against the case above: only the omission differs, so the attribute
    follows the parameters rather than a list of names of its own.
    """
    validator = SerializerValidator(_TenantIn, excluded=frozenset({"tenant"}))

    assert validator.parameters().names() == frozenset({"title"})
    assert validator.unsendable == frozenset({"tenant"})


def test_a_required_field_named_result_is_unsendable() -> None:
    """``result`` is a dispatcher seed name (``RESERVED_POOL_SEEDS``), like ``user``."""
    assert _validator_of(_RequiredResultIn).unsendable == frozenset({"result"})


def test_a_hidden_field_is_not_unsendable() -> None:
    """A ``HiddenField`` is no input at all, so a call is never asked for it."""
    assert _validator_of(_HiddenUserIn).unsendable == frozenset()


@pytest.mark.django_db
def test_a_partial_spec_names_the_same_fields() -> None:
    """Whether a call may leave the field out is the spec's ``partial``, not this attribute's."""
    assert _validator_of(_RequiredUserIn, partial=True).unsendable == frozenset({"user"})


@pytest.mark.django_db
def test_a_many_specs_row_fields_are_read_through_the_row_serializer() -> None:
    """The Validator of a ``many`` spec holds the row serializer, so a row is what is read.

    A row's required ``user`` is named because the kernel's ``dispatch`` cannot
    send it either: ``parameters()`` omits it from the row's own Parameters, and
    a call over ``items`` is refused for it under ``REJECT`` (an unknown
    argument) and under ``IGNORE`` (required). A row field named like no seed is
    no different from the single-object case: declared, so not named.
    """
    spec = _spec(_RequiredUserIn, many=True)
    principal = AnonymousUser()

    for policy in (UnknownArguments.REJECT, UnknownArguments.IGNORE):
        with pytest.raises(InvalidArguments) as excinfo:
            dispatch(
                spec,
                principal=principal,
                arguments={"items": [{"title": "t", "user": 1}]},
                grant=Grant(spec, principal),
                unknown_arguments=policy,
            )
        assert set(excinfo.value.detail["items"][0]) == {"user"}, policy
    assert _validator_of(_RequiredUserIn, many=True).unsendable == frozenset({"user"})
    assert _validator_of(_TenantIn, many=True).unsendable == frozenset()


@pytest.mark.django_db
def test_a_lenient_validator_names_the_same_fields() -> None:
    """``lenient`` relaxes what is declared, not which names are declared at all."""
    validator = SerializerValidator(_RequiredUserIn, lenient=True)

    assert validator.parameters().names() == frozenset({"title"})
    assert validator.unsendable == frozenset({"user"})


@pytest.mark.django_db
def test_a_reader_holding_the_seat_reads_the_override() -> None:
    """What a transport reads off the spec's ``validator`` is this class's answer."""
    seat: Validator = _spec(_RequiredUserIn).validator

    assert getattr(seat, "unsendable", frozenset()) == frozenset({"user"})


class _Bare(Validator):
    """A Validator defining only what the ABC requires, as a third party's would."""

    def parameters(self) -> Parameters:
        return Parameters.of()

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return dict(arguments)


@pytest.mark.xfail(
    strict=True,
    raises=AttributeError,
    reason=(
        "kernel item 13: Validator.unsendable is not on the kernel's Validator ABC yet, "
        "so a Validator that does not define it has no empty default to answer"
    ),
)
def test_a_validator_that_does_not_define_it_answers_the_empty_default() -> None:
    """Once the kernel's ABC declares the default, a reader stops needing ``getattr``.

    Asked of a subclass defining only the abstract methods, so a kernel
    release that adds the property to its own validators alone still fails
    here. Strict, so the release that declares it on the ABC turns this green
    and fails the suite until the xfail is lifted and the ``getattr`` readers
    move.
    """
    validator: Any = _Bare()

    assert validator.unsendable == frozenset()
