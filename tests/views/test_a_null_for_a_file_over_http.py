"""Over HTTP, a client's ``null`` for a file field clears the file where the field allows it.

A ``null`` for a field declaring ``allow_null`` is the client asking for no
file, so the ``SerializerValidator`` hands the service ``""`` for it: what the
model field stores for no file, which ``save()``, ``create`` and ``update`` take
as it is and the kernel's ``update_from_input`` reads as a clear (``None`` keeps
the file the row holds). A field that does not allow the ``null`` refuses it.
Every case drives a real file on a real row through the view, and reads the
row back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from django import forms
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django_service_specs import (
    FormValidator,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.mutations.update_from_input import update_from_input
from rest_framework import serializers
from rest_framework.test import APIRequestFactory
from rest_framework_dataclasses.serializers import DataclassSerializer

from django_spec_rest import ServiceCreateView, ServiceUpdateView
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Document

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_HANDED: dict[str, Any] = {}


def _document(*, pk: int) -> Document | None:
    return Document.objects.filter(pk=pk).first()


_DOCUMENT = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=_document,
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
)


class _MayClear(serializers.Serializer):
    upload = serializers.FileField(allow_null=True, required=False)
    title = serializers.CharField(allow_null=True, required=False)


class _MayNotClear(serializers.Serializer):
    upload = serializers.FileField(required=False)


class _ImageMayClear(serializers.Serializer):
    upload = serializers.ImageField(allow_null=True, required=False)


class _Sourced(serializers.Serializer):
    wire = serializers.FileField(source="upload", allow_null=True, required=False)


class _Dotted(serializers.Serializer):
    wire = serializers.FileField(source="nest.upload", allow_null=True, required=False)


class _Child(serializers.Serializer):
    upload = serializers.FileField(allow_null=True, required=False)
    label = serializers.CharField(required=False)


class _Nested(serializers.Serializer):
    child = _Child(required=False, allow_null=True)


class _Flattened(serializers.Serializer):
    flat = _Child(source="*", required=False)


class _NestedMany(serializers.Serializer):
    children = _Child(many=True, required=False, allow_null=True)


class _ReplacesTheNesting(serializers.Serializer):
    wire = serializers.FileField(source="nest.upload", allow_null=True, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        return {"nest": 5}


class _ReturnsAnObject(serializers.Serializer):
    upload = serializers.FileField(allow_null=True, required=False)

    def validate(self, attrs: dict[str, Any]) -> Any:
        return object()


@dataclass
class _Upload:
    upload: Any = None


class _Model(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = ["upload"]
        extra_kwargs = {"upload": {"allow_null": True, "required": False}}


class _Form(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["upload"]


def _update(*, instance: Document, data: Any) -> Document:
    _HANDED["data"] = data
    return update_from_input(instance, data).instance


def _save(*, serializer: serializers.Serializer) -> Any:
    return serializer.save()


def _read_upload(*, instance: Document, upload: Any = "unsent") -> Document:
    _HANDED["upload"] = upload
    return instance


def _spec(input_serializer: type, service: Any = _update) -> ServiceSpec:
    return ServiceSpec(
        service=service,
        validator=SerializerValidator(input_serializer),
        instance_selector_spec=_DOCUMENT,
        permissions=_OPEN,
    )


def _held(settings: Any, tmp_path: Any) -> Document:
    settings.MEDIA_ROOT = str(tmp_path)
    document = Document()
    document.upload.save("held.txt", ContentFile(b"held"))
    return document


def _patch(spec: ServiceSpec, document: Document, body: Any, form_format: str = "json") -> Any:
    request = _factory.patch(f"/documents/{document.pk}/", body, format=form_format)
    response = ServiceUpdateView.as_view(spec=spec)(request, pk=document.pk)
    document.refresh_from_db()
    return response


def test_a_null_clears_the_file(settings: Any, tmp_path: Any) -> None:
    document = _held(settings, tmp_path)
    assert _patch(_spec(_MayClear), document, {"upload": None}).status_code == 200
    assert document.upload.name == ""


def test_a_null_clears_an_image_field_s_file(settings: Any, tmp_path: Any) -> None:
    document = _held(settings, tmp_path)
    assert _patch(_spec(_ImageMayClear), document, {"upload": None}).status_code == 200
    assert document.upload.name == ""


def test_a_null_on_a_field_not_allowing_it_is_refused_and_the_file_stays(
    settings: Any, tmp_path: Any
) -> None:
    document = _held(settings, tmp_path)
    response = _patch(_spec(_MayNotClear), document, {"upload": None})
    assert response.status_code == 400
    assert list(response.data) == ["upload"]
    assert document.upload.name.startswith("documents/held")


def test_a_patch_leaving_the_file_out_keeps_it(settings: Any, tmp_path: Any) -> None:
    """Fails with a key the client did not send read as its ``None``."""
    document = _held(settings, tmp_path)
    assert _patch(_spec(_MayClear), document, {"title": "t"}).status_code == 200
    assert document.upload.name.startswith("documents/held")
    assert _HANDED["data"] == {"title": "t"}


def test_a_null_for_another_field_stays_none(settings: Any, tmp_path: Any) -> None:
    """Fails with every validated ``None`` read as a file's."""
    document = _held(settings, tmp_path)
    _patch(_spec(_MayClear, _read_title), document, {"title": None})
    assert _HANDED["title"] is None


def _read_title(*, instance: Document, title: Any = "unsent") -> Document:
    _HANDED["title"] = title
    return instance


def test_serializer_save_clears_the_file_as_it_did(settings: Any, tmp_path: Any) -> None:
    """The bound serializer keeps DRF's ``None``, which its ``save()`` writes as no file."""
    document = _held(settings, tmp_path)
    assert _patch(_spec(_Model, _save), document, {"upload": None}).status_code == 200
    assert document.upload.name == ""


def test_the_parameter_named_like_the_field_is_handed_the_empty_file(
    settings: Any, tmp_path: Any
) -> None:
    document = _held(settings, tmp_path)
    _patch(_spec(_MayClear, _read_upload), document, {"upload": None})
    assert _HANDED["upload"] == ""


def test_a_field_s_source_is_the_key_cleared(settings: Any, tmp_path: Any) -> None:
    document = _held(settings, tmp_path)
    assert _patch(_spec(_Sourced), document, {"wire": None}).status_code == 200
    assert document.upload.name == ""


def test_a_dotted_source_is_cleared_where_it_nests(settings: Any, tmp_path: Any) -> None:
    document = _held(settings, tmp_path)
    _patch(_spec(_Dotted, _read_data), document, {"wire": None})
    assert _HANDED["data"] == {"nest": {"upload": ""}}


def _read_data(*, instance: Document, data: Any) -> Document:
    _HANDED["data"] = data
    return instance


def test_a_nested_serializer_s_file_is_cleared(settings: Any, tmp_path: Any) -> None:
    document = _held(settings, tmp_path)
    _patch(_spec(_Nested, _read_data), document, {"child": {"upload": None, "label": "x"}})
    assert _HANDED["data"] == {"child": {"upload": "", "label": "x"}}


def test_a_null_nested_serializer_stays_null(settings: Any, tmp_path: Any) -> None:
    document = _held(settings, tmp_path)
    _patch(_spec(_Nested, _read_data), document, {"child": None})
    assert _HANDED["data"] == {"child": None}


def test_a_flattened_serializer_s_file_is_cleared(settings: Any, tmp_path: Any) -> None:
    document = _held(settings, tmp_path)
    assert _patch(_spec(_Flattened), document, {"flat": {"upload": None}}).status_code == 200
    assert document.upload.name == ""


def test_each_row_of_a_nested_many_is_cleared(settings: Any, tmp_path: Any) -> None:
    document = _held(settings, tmp_path)
    body = {"children": [{"upload": None}, {"label": "kept"}]}
    _patch(_spec(_NestedMany, _read_data), document, body)
    assert _HANDED["data"] == {"children": [{"upload": ""}, {"label": "kept"}]}


def test_a_null_nested_many_stays_null(settings: Any, tmp_path: Any) -> None:
    """Fails with the nested list's value iterated without asking whether it is one."""
    document = _held(settings, tmp_path)
    _patch(_spec(_NestedMany, _read_data), document, {"children": None})
    assert _HANDED["data"] == {"children": None}


def test_a_nesting_a_validate_replaced_is_left_as_built(settings: Any, tmp_path: Any) -> None:
    """Fails with the walk reading a key of a value that is no mapping."""
    document = _held(settings, tmp_path)
    _patch(_spec(_ReplacesTheNesting, _read_data), document, {"wire": None})
    assert _HANDED["data"] == {"nest": 5}


def test_an_object_a_validate_returns_is_data_as_built(settings: Any, tmp_path: Any) -> None:
    document = _held(settings, tmp_path)
    _patch(_spec(_ReturnsAnObject, _read_data), document, {"upload": None})
    assert type(_HANDED["data"]) is object


def test_data_with_nothing_to_clear_is_the_bound_serializer_s_own(
    settings: Any, tmp_path: Any
) -> None:
    """A copy is made only where a file is cleared."""
    seen: dict[str, Any] = {}

    def service(*, instance: Document, data: Any, serializer: Any) -> Document:
        seen["same"] = data is serializer.validated_data
        return instance

    document = _held(settings, tmp_path)
    _patch(_spec(_NestedMany, service), document, {"children": [{"label": "kept"}]})
    assert seen == {"same": True}


def test_a_view_hook_s_null_clears_the_file_too(settings: Any, tmp_path: Any) -> None:
    """The server's value for a field is validated apart, and handed on as the client's is."""

    class _View(ServiceUpdateView):
        def get_input_data(self, request: Any) -> dict[str, Any]:
            return {"upload": None}

    document = _held(settings, tmp_path)
    request = _factory.patch(f"/documents/{document.pk}/", {"title": "t"}, format="json")
    spec = _spec(_MayClear, _read_upload)
    assert _View.as_view(spec=spec)(request, pk=document.pk).status_code == 200
    assert _HANDED["upload"] == ""


def test_a_create_s_null_stores_no_file(settings: Any, tmp_path: Any) -> None:
    """The service writes ``data`` through the model itself, as the quickstart does."""
    settings.MEDIA_ROOT = str(tmp_path)

    def create(*, upload: Any, data: dict[str, Any]) -> Document:
        _HANDED["upload"] = upload
        return Document.objects.create(**data)

    spec = ServiceSpec(service=create, validator=SerializerValidator(_MayClear), permissions=_OPEN)
    request = _factory.post("/documents/", {"upload": None}, format="json")
    assert ServiceCreateView.as_view(spec=spec)(request).status_code == 201
    assert _HANDED["upload"] == ""
    assert Document.objects.get().upload.name == ""


def _set_and_save(*, instance: Document, data: dict[str, Any]) -> Document:
    for name, value in data.items():
        setattr(instance, name, value)
    instance.save()
    return instance


def _queryset_update(*, instance: Document, data: dict[str, Any]) -> Document:
    Document.objects.filter(pk=instance.pk).update(**data)
    return instance


@pytest.mark.parametrize("service", [_set_and_save, _queryset_update])
def test_a_service_writing_data_itself_clears_the_file(
    settings: Any, tmp_path: Any, service: Any
) -> None:
    """``setattr`` then ``save()`` raises on ``False``, and ``update(**data)`` stores ``'False'``."""
    document = _held(settings, tmp_path)
    assert _patch(_spec(_MayClear, service), document, {"upload": None}).status_code == 200
    assert document.upload.name == ""


class _ClearedByDefault(serializers.Serializer):
    upload = serializers.FileField(allow_null=True, default=None)


def test_a_put_leaving_out_a_file_defaulting_to_none_clears_it(
    settings: Any, tmp_path: Any
) -> None:
    """DRF fills the omitted field with its ``None`` default, which reads as a ``null`` sent."""
    document = _held(settings, tmp_path)
    request = _factory.put(f"/documents/{document.pk}/", {}, format="json")
    assert (
        ServiceUpdateView.as_view(spec=_spec(_ClearedByDefault))(
            request, pk=document.pk
        ).status_code
        == 200
    )
    document.refresh_from_db()
    assert document.upload.name == ""


def test_a_patch_leaving_out_a_file_defaulting_to_none_keeps_it(
    settings: Any, tmp_path: Any
) -> None:
    """A partial call fills no default, so the unsent key is no ``null``."""
    document = _held(settings, tmp_path)
    assert _patch(_spec(_ClearedByDefault), document, {}).status_code == 200
    assert document.upload.name.startswith("documents/held")


def test_a_dataclass_s_field_keeps_its_none(settings: Any, tmp_path: Any) -> None:
    """A dataclass instance is as built: its field keeps the ``None``, ``""`` being no value of it."""

    class _Declared(DataclassSerializer):
        upload = serializers.FileField(allow_null=True, required=False)

        class Meta:
            dataclass = _Upload

    document = _held(settings, tmp_path)
    request = _factory.put(f"/documents/{document.pk}/", {"upload": None}, format="json")
    response = ServiceUpdateView.as_view(spec=_spec(_Declared, _read_both))(request, pk=document.pk)
    assert response.status_code == 200
    assert _HANDED["data"].upload is None
    assert _HANDED["upload"] is None


def _read_both(*, instance: Document, data: Any, upload: Any) -> Document:
    _HANDED["data"] = data
    _HANDED["upload"] = upload
    return instance


def test_a_kernel_dispatch_off_http_clears_as_the_edge_does(settings: Any, tmp_path: Any) -> None:
    """The Validator's answer, not the edge's: every transport over it is handed ``""``."""
    document = _held(settings, tmp_path)
    dispatch(_spec(_MayClear), principal=None, arguments={"pk": document.pk, "upload": None})
    document.refresh_from_db()
    assert document.upload.name == ""


def test_a_form_s_blank_keeps_the_file(settings: Any, tmp_path: Any) -> None:
    """DRF reads a form's blank as ``None``: a form never sends a null, so nothing clears."""
    document = _held(settings, tmp_path)
    assert _patch(_spec(_MayClear), document, {"upload": ""}, "multipart").status_code == 200
    assert document.upload.name.startswith("documents/held")


def test_a_form_s_clear_checkbox_means_nothing_to_a_serializer(
    settings: Any, tmp_path: Any
) -> None:
    document = _held(settings, tmp_path)
    assert (
        _patch(_spec(_MayClear), document, {"upload-clear": "on"}, "multipart").status_code == 200
    )
    assert document.upload.name.startswith("documents/held")


@pytest.mark.parametrize("sent", ["true", "on"])
def test_a_form_validator_s_clear_checkbox_still_clears(
    settings: Any, tmp_path: Any, sent: str
) -> None:
    """A browser's checked box sends ``on``, which the edge reads as ``True`` for a form body alone.

    The ``on`` case fails with a 400 on ``upload-clear`` (``Enter true, false, 1 or 0.``)
    without ``_checked_boxes`` in ``kernel_edge``.
    """
    spec = ServiceSpec(
        service=_update,
        validator=FormValidator(_Form),
        instance_selector_spec=_DOCUMENT,
        permissions=_OPEN,
    )
    document = _held(settings, tmp_path)
    response = _patch(spec, document, {"upload-clear": sent}, "multipart")
    assert response.status_code == 200, response.data
    assert document.upload.name == ""


def test_an_upload_replaces_the_file(settings: Any, tmp_path: Any) -> None:
    document = _held(settings, tmp_path)
    upload = SimpleUploadedFile("new.txt", b"new")
    assert _patch(_spec(_MayClear), document, {"upload": upload}, "multipart").status_code == 200
    assert document.upload.name.startswith("documents/new")


def test_an_upload_off_http_arrives_as_the_file_itself(settings: Any, tmp_path: Any) -> None:
    """Fails with ``""`` handed for the file, were the empty file returned for every file field's value.

    Off HTTP only: a multipart body is a ``MultiValueDict``, which never reaches
    the clear (test_a_form_s_blank_keeps_the_file), so a dict of arguments holding
    the file is the Validator's non-``None`` arm.
    """
    document = _held(settings, tmp_path)
    upload = SimpleUploadedFile("new.txt", b"new")
    dispatch(
        _spec(_MayClear, _read_upload),
        principal=None,
        arguments={"pk": document.pk, "upload": upload},
    )
    assert _HANDED["upload"].name == "new.txt"
    assert _HANDED["upload"].read() == b"new"


def test_a_bulk_row_s_null_is_handed_the_empty_file(settings: Any, tmp_path: Any) -> None:
    def create(*, items: list[dict[str, Any]], data: list[Any]) -> list[Any]:
        _HANDED["items"] = items
        _HANDED["data"] = data
        return []

    spec = ServiceSpec(
        service=create,
        validator=SerializerValidator(_MayClear),
        many=True,
        permissions=_OPEN,
    )
    request = _factory.post("/documents/", [{"upload": None}, {"title": "t"}], format="json")
    response = ServiceCreateView.as_view(spec=spec)(request)
    assert response.status_code == 201, response.data
    assert _HANDED["items"] == [{"upload": ""}, {"title": "t"}]
    assert _HANDED["data"] == [{"upload": ""}, {"title": "t"}]
