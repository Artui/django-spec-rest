"""Declaring and registering a kernel spec never needs the database.

A kernel spec asks its Validator's ``parameters()`` when the spec's own are
read, by a schema or a dispatch, and never as it is declared or registered.
So a spec declared at import, before ``migrate`` has made a table, whose
serializer's fields query one, look up a row that is not there yet or read a
request no import has, registers; the refusal a description makes is made
when the call describes it.

A ``many`` spec's rows are bound by the list serializer DRF builds for its
input, which builds the row serializer too. One that cannot be built with no
call still registers, and the list serializer that validates the call holds the
list to the bound it declares.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django_service_specs import Parameter, Parameters, ServiceSpec, SpecRegistry, Unrestricted
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS
from rest_framework import serializers

from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Tag

FAILING: dict[str, str | None] = {"how": None}


def _missing_table() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM a_table_migrate_has_not_made")


_FAILURES: dict[str, Any] = {
    # A table ``migrate`` has not made yet: ``OperationalError``, a ``DatabaseError``.
    "missing-table": _missing_table,
    # A row no fixture has loaded yet: the model's ``DoesNotExist``.
    "missing-row": lambda: Tag.objects.get(name="absent"),
    # The request a declaration has not got, read three ways.
    "attribute": lambda context: context["request"].user,
    "key": lambda context: context["absent"],
    "subscript": lambda context: context["request"]["user"],
}


def _fail(context: Any) -> None:
    how = FAILING["how"]
    if how in ("missing-table", "missing-row"):
        _FAILURES[how]()
    elif how is not None:
        _FAILURES[how](context)


class _FieldsFromTheDatabase(serializers.Serializer):
    title = serializers.CharField()

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        _fail(self.context)
        return fields


class _BuiltFromTheDatabase(serializers.Serializer):
    title = serializers.CharField()

    @classmethod
    def many_init(cls, *args: Any, **kwargs: Any) -> serializers.ListSerializer:
        return super().many_init(*args, max_length=2, **kwargs)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        _fail(self.context)


def _service(*, data: Any) -> Any:
    return dict(data)


def _rows(*, data: Any) -> Any:
    return list(data)


def _many_spec() -> ServiceSpec:
    return ServiceSpec(
        service=_rows,
        permissions=(Unrestricted(),),
        validator=SerializerValidator(_BuiltFromTheDatabase),
        many=True,
        atomic=False,
    )


def _spec() -> ServiceSpec:
    # A read named like the writable field ``title``: refused where the
    # serializer's fields can be read.
    return ServiceSpec(
        service=_service,
        permissions=(Unrestricted(),),
        validator=SerializerValidator(_FieldsFromTheDatabase),
        reads=Parameters.of(Parameter("title", "string")),
        atomic=False,
    )


@pytest.fixture(autouse=True)
def _fields_read() -> Any:
    yield
    FAILING["how"] = None


@pytest.mark.django_db
@pytest.mark.parametrize("how", list(_FAILURES))
def test_a_spec_whose_fields_cannot_be_read_without_a_call_registers(how: str) -> None:
    FAILING["how"] = how

    SpecRegistry().register("titled", _spec())


@pytest.mark.django_db
def test_with_its_fields_read_the_read_is_refused_by_its_parameters() -> None:
    """The kernel reads a Validator's ``parameters()`` when the spec's are asked,
    not when it is declared or registered, so the refusal is there."""
    spec = _spec()
    SpecRegistry().register("titled", spec)

    with pytest.raises(ImproperlyConfigured, match=r"\['title'\] are declared by two sources"):
        spec.parameters()


@pytest.mark.django_db
def test_declared_before_the_table_exists_it_is_refused_at_dispatch() -> None:
    FAILING["how"] = "missing-table"
    spec = _spec()
    SpecRegistry().register("titled", spec)

    FAILING["how"] = None
    with pytest.raises(ImproperlyConfigured, match=r"\['title'\] are declared by two sources"):
        dispatch(spec, principal=AnonymousUser(), arguments={"title": "a"})


@pytest.mark.django_db
@pytest.mark.parametrize("how", list(_FAILURES))
def test_a_many_spec_whose_serializer_cannot_be_built_without_a_call_registers(how: str) -> None:
    FAILING["how"] = how

    SpecRegistry().register("rows", _many_spec())


@pytest.mark.django_db
def test_declared_before_the_table_exists_its_list_is_still_bounded() -> None:
    FAILING["how"] = "missing-table"
    spec = _many_spec()
    SpecRegistry().register("rows", spec)

    FAILING["how"] = None
    # The spec declares no bound of its own, so the list serializer that
    # validates the call is what refuses the third row.
    assert spec.many_max_length is None
    rows = [{"title": "a"}, {"title": "b"}, {"title": "c"}]
    with pytest.raises(InvalidArguments) as excinfo:
        dispatch(spec, principal=AnonymousUser(), arguments={"items": rows})
    # The list serializer's own refusal, under the spec's ``many_argument``.
    (message,) = excinfo.value.detail["items"][NON_FIELD_ERRORS]
    assert (str(message), message.code) == (
        "Ensure this field has no more than 2 elements.",
        "max_length",
    )
