"""``ServiceDeleteView`` over a kernel spec."""

from __future__ import annotations

from typing import Any

import pytest
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceError,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceDeleteView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_PRESENTER = SerializerPresenter(AuthorSerializer)

_AUTHOR = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
)


def _delete(*, instance: Author) -> None:
    instance.delete()


def _view(service: Any, **seats: Any) -> Any:
    attrs = {key: seats.pop(key) for key in ("success_status",) if key in seats}
    spec = ServiceSpec(service=service, permissions=_OPEN, instance_selector_spec=_AUTHOR, **seats)
    return type("_View", (ServiceDeleteView,), {"spec": spec, **attrs}).as_view()


class TestServiceDeleteView:
    def test_a_delete_returning_nothing_answers_204(self) -> None:
        """Even with a presenter: nothing is presented, never the deleted row."""
        author = Author.objects.create(name="Gone")
        response = _view(_delete, presenter=_PRESENTER)(factory.delete("/"), pk=author.pk)
        assert response.status_code == 204
        assert response.data is None
        assert not Author.objects.exists()

    def test_404_when_missing(self) -> None:
        assert _view(_delete)(factory.delete("/"), pk=999).status_code == 404

    def test_with_a_validator_reading_the_body(self) -> None:
        class _Reason(serializers.Serializer):
            reason = serializers.CharField()

        seen: dict[str, Any] = {}

        def delete(*, instance: Author, data: dict[str, Any]) -> None:
            seen["reason"] = data["reason"]
            instance.delete()

        author = Author.objects.create(name="Gone")
        view = _view(delete, validator=SerializerValidator(_Reason))
        response = view(factory.delete("/", {"reason": "spam"}, format="json"), pk=author.pk)
        assert response.status_code == 204
        assert seen == {"reason": "spam"}

    def test_service_error_maps_to_422(self) -> None:
        def boom(*, instance: Author) -> None:
            raise ServiceError("in use")

        author = Author.objects.create(name="Kept")
        assert _view(boom, atomic=False)(factory.delete("/"), pk=author.pk).status_code == 422
        assert Author.objects.filter(pk=author.pk).exists()

    def test_an_output_selector_re_read_is_presented(self) -> None:
        archive = Author.objects.create(name="archive")

        def soft_delete(*, instance: Author) -> int:
            instance.delete()
            return archive.pk

        author = Author.objects.create(name="Gone")
        view = _view(
            soft_delete,
            output_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, result: Author.objects.get(pk=result),
                presenter=_PRESENTER,
            ),
        )
        response = view(factory.delete("/"), pk=author.pk)
        assert response.status_code == 200
        assert response.data == {"id": archive.pk, "name": "archive"}

    def test_a_destroy_presenting_a_row_answers_200_rather_than_204(self) -> None:
        """A ``204`` carries no body, so a destroy whose service returns a row
        it presents answers ``200``."""

        def soft_delete(*, instance: Author) -> Author:
            instance.name = "[deleted]"
            instance.save(update_fields=["name"])
            return instance

        author = Author.objects.create(name="Gone")
        response = _view(soft_delete, presenter=_PRESENTER)(factory.delete("/"), pk=author.pk)
        assert response.status_code == 200
        assert response.data == {"id": author.pk, "name": "[deleted]"}

    def test_a_destroy_returning_a_raw_value_answers_200_rather_than_204(self) -> None:
        def count(*, instance: Author) -> dict[str, int]:
            instance.delete()
            return {"deleted": 1}

        author = Author.objects.create(name="Gone")
        response = _view(count)(factory.delete("/"), pk=author.pk)
        assert response.status_code == 200
        assert response.data == {"deleted": 1}

    def test_a_set_status_holds_for_an_answer_with_nothing_to_present(self) -> None:
        author = Author.objects.create(name="Gone")
        view = _view(_delete, presenter=_PRESENTER, success_status=202)
        response = view(factory.delete("/"), pk=author.pk)
        assert response.status_code == 202
        assert response.data is None

    def test_a_set_status_holds_for_a_presented_value(self) -> None:
        author = Author.objects.create(name="Gone")
        view = _view(lambda *, instance: {"ok": True}, success_status=202)
        assert view(factory.delete("/"), pk=author.pk).status_code == 202
