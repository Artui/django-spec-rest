"""``caller_serializer_class``: the author's serializer less what ``input_data`` fills."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from drf_spectacular.drainage import get_override
from rest_framework import serializers

from django_spec_rest.openapi._caller_serializer_class import caller_serializer_class
from tests.testapp.serializers import AuthorSerializer


class _Fields(serializers.Serializer):
    a = serializers.CharField()
    b = serializers.CharField()
    c = serializers.CharField()
    a_b = serializers.CharField()
    b_c = serializers.CharField()
    tenant = serializers.CharField()
    note = serializers.CharField()
    optional_note = serializers.CharField()
    tenant_optional = serializers.CharField()
    camelCase = serializers.CharField()
    my_serializer = serializers.CharField()


def _name(owned: Iterable[str] = (), relaxed: Iterable[str] = ()) -> str:
    derived = caller_serializer_class(
        _Fields, "Fields", owned=frozenset(owned), relaxed=frozenset(relaxed)
    )
    return derived.Meta.ref_name


def test_owned_and_relaxed_fields_are_named_by_section() -> None:
    assert _name({"tenant"}) == "FieldsLessTenant"
    assert _name(relaxed={"tenant"}) == "FieldsOptionalTenant"
    assert _name({"tenant", "a_b"}, {"note"}) == "FieldsLessAB_Tenant__OptionalNote"


def test_fields_are_joined_so_no_two_sets_share_a_name() -> None:
    assert _name({"a_b", "c"}) == "FieldsLessAB_C"
    assert _name({"a", "b_c"}) == "FieldsLessA_BC"


def test_the_two_sections_cannot_be_read_as_one() -> None:
    assert _name({"tenant_optional"}, {"note"}) == "FieldsLessTenantOptional__OptionalNote"
    assert _name({"tenant"}, {"optional_note"}) == "FieldsLessTenant__OptionalOptionalNote"


def test_a_name_that_is_not_lower_snake_case_is_spelled_in_hex() -> None:
    # ``camelCase`` in PascalCase would read back as ``camel_case``.
    assert _name({"camelCase"}) == "FieldsLess0" + b"camelCase".hex()


def test_a_name_ending_serializer_keeps_it() -> None:
    # drf-spectacular takes one ``Serializer`` off every component name.
    assert _name({"my_serializer"}) == "FieldsLessMySerializerSerializer"


def test_the_derived_fields_drop_the_owned_and_relax_the_reached() -> None:
    derived = caller_serializer_class(
        _Fields, "Fields", owned=frozenset({"a"}), relaxed=frozenset({"b"})
    )
    fields: Any = derived().fields
    assert "a" not in fields
    assert fields["b"].required is False
    assert fields["c"].required is True
    # The author's class is untouched.
    assert _Fields().fields["b"].required is True


def test_the_name_outranks_an_inherited_component_name() -> None:
    derived = caller_serializer_class(
        _Fields, "Fields", owned=frozenset({"a"}), relaxed=frozenset()
    )
    assert get_override(derived, "component_name") == "FieldsLessA"


def test_a_model_serializer_keeps_its_meta() -> None:
    derived = caller_serializer_class(
        AuthorSerializer, "Author", owned=frozenset({"name"}), relaxed=frozenset()
    )
    assert derived.Meta.model is AuthorSerializer.Meta.model
    assert set(derived().fields) == {"id"}


def test_one_key_is_one_class() -> None:
    key: dict[str, Any] = {"owned": frozenset({"a"}), "relaxed": frozenset({"b"})}
    assert caller_serializer_class(_Fields, "Fields", **key) is caller_serializer_class(
        _Fields, "Fields", **key
    )
