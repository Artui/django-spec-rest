from __future__ import annotations

from typing import Any

import pytest
from django.urls import path, register_converter
from django_service_specs import SelectorKind, SelectorSpec, ServiceSpec, Unrestricted
from rest_framework import serializers
from rest_framework.test import APIClient

from django_spec_rest import ServiceCreateView, ServiceUpdateView
from django_spec_rest.dispatch import kernel_edge
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db

_OPEN = (Unrestricted(),)
_SEEN: dict[str, Any] = {}


class _Hashed:
    """A converter whose Python value is not its wire value: ``h42`` is ``42``."""

    regex = "h[0-9]+"

    def to_python(self, value: str) -> int:
        return int(value[1:])

    def to_url(self, value: int) -> str:
        return f"h{value}"


register_converter(_Hashed, "hashed_namesake")


class _HashedField(serializers.IntegerField):
    def to_internal_value(self, data: Any) -> int:
        if not isinstance(data, str) or not data.startswith("h"):
            self.fail("invalid")
        return int(data[1:])


class _Comment(serializers.Serializer):
    id = _HashedField(required=False)
    comment = serializers.CharField(required=False)


def _update(*, instance: Author, data: Any) -> None:
    _SEEN["instance"], _SEEN["data"] = instance, dict(data)


def _create(*, data: Any) -> None:
    _SEEN["data"] = dict(data)


def _the_row(*, id: int) -> Author | None:  # noqa: A002
    return Author.objects.filter(pk=id).first()


class _Open:
    permission_classes: Any = []
    authentication_classes: Any = []


class _Update(_Open, ServiceUpdateView):
    spec = ServiceSpec(
        service=_update,
        validator=SerializerValidator(_Comment),
        partial=True,
        permissions=_OPEN,
        allow_none=True,
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=_the_row,
            kwargs=lambda view: {"id": view.kwargs["id"]},
        ),
    )


class _Create(_Open, ServiceCreateView):
    spec = ServiceSpec(
        service=_create,
        validator=SerializerValidator(_Comment),
        permissions=_OPEN,
        allow_none=True,
    )


urlpatterns = [
    path("u/<hashed_namesake:id>/", _Update.as_view()),
    path("c/<hashed_namesake:id>/", _Create.as_view()),
]


@pytest.fixture
def row() -> Author:
    _SEEN.clear()
    return Author.objects.create(name="a")


@pytest.fixture
def edge(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    real = kernel_edge.kernel_arguments
    made: dict[str, Any] = {}

    def recording(*args: Any, **kwargs: Any) -> Any:
        made["arguments"], made["bound"] = result = real(*args, **kwargs)
        return result

    monkeypatch.setattr(kernel_edge, "kernel_arguments", recording)
    return made


@pytest.mark.urls(__name__)
class TestACaptureNamedLikeAFieldIsTheCallers:
    @pytest.mark.parametrize("fmt", ["json", "multipart"])
    def test_a_patch_without_the_key_answers_2xx(self, row: Author, fmt: str) -> None:
        response = APIClient().patch(f"/u/h{row.pk}/", {"comment": "hi"}, format=fmt)
        assert response.status_code == 204, response.data
        assert _SEEN["instance"] == row
        assert _SEEN["data"] == {"comment": "hi"}

    @pytest.mark.parametrize("fmt", ["json", "multipart"])
    def test_a_create_without_the_key_answers_2xx(self, row: Author, fmt: str) -> None:
        response = APIClient().post("/c/h42/", {"comment": "hi"}, format=fmt)
        assert response.status_code == 204, response.data
        assert _SEEN["data"] == {"comment": "hi"}

    def test_the_caller_s_own_value_reaches_the_field(self, row: Author) -> None:
        response = APIClient().post("/c/h42/", {"id": "h7"}, format="multipart")
        assert response.status_code == 204, response.data
        assert _SEEN["data"] == {"id": 7}

    def test_the_kernel_and_the_serializer_agree_on_the_field(
        self, row: Author, edge: dict[str, Any]
    ) -> None:
        response = APIClient().patch(f"/u/h{row.pk}/", {"comment": "hi"}, format="json")
        assert response.status_code == 204, response.data
        _, body = edge["bound"]
        assert "id" not in edge["arguments"]
        assert "id" not in body
