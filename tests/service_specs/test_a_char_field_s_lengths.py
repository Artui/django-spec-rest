from __future__ import annotations

from typing import Any

from rest_framework import serializers

from django_spec_rest.service_specs.serializer_validator import SerializerValidator


class _Inner(serializers.Serializer):
    code = serializers.CharField(max_length=8, min_length=3)


class _Outer(serializers.Serializer):
    title = serializers.CharField(max_length=100, min_length=2)
    email = serializers.EmailField(max_length=254)
    note = serializers.CharField()
    inner = _Inner()
    rows = _Inner(many=True)


def _extra(name: str) -> Any:
    return SerializerValidator(_Outer).parameters().get(name).json_schema_extra


def test_a_char_field_states_its_lengths() -> None:
    assert _extra("title") == {"maxLength": 100, "minLength": 2}


def test_a_char_field_subclass_states_its_length() -> None:
    assert _extra("email") == {"maxLength": 254}


def test_a_char_field_with_no_lengths_states_none() -> None:
    assert not _extra("note")


def test_a_nested_serializer_s_char_field_states_its_lengths() -> None:
    inner = SerializerValidator(_Outer).parameters().get("inner").fields.get("code")
    assert inner.json_schema_extra == {"maxLength": 8, "minLength": 3}


def test_a_list_serializer_row_s_char_field_states_its_lengths() -> None:
    rows = SerializerValidator(_Outer).parameters().get("rows").items
    assert rows.get("code").json_schema_extra == {"maxLength": 8, "minLength": 3}


class _Blank(serializers.Serializer):
    title = serializers.CharField(max_length=100, min_length=2, allow_blank=True)


def test_a_field_a_blank_passes_states_no_minimum() -> None:
    """DRF takes a blank before its validators run, so ``minLength`` would refuse what it takes."""
    extra = SerializerValidator(_Blank).parameters().get("title").json_schema_extra
    assert extra == {"maxLength": 100}
