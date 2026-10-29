"""A ``create_model`` factory as a kernel spec's service, over a real HTTP request.

Protects against view-layer regressions that would break the closure's shape
(``is_async`` detection, keyword filtering, response rendering).
"""

from __future__ import annotations

import pytest
from django_service_specs import ServiceSpec, Unrestricted, create_model
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceCreateView
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer


class _CreateAuthorInput(serializers.Serializer):
    name = serializers.CharField()


class _CreateAuthorView(ServiceCreateView):
    spec = ServiceSpec(
        service=create_model(Author),
        permissions=(Unrestricted(),),
        validator=SerializerValidator(_CreateAuthorInput),
        presenter=SerializerPresenter(AuthorSerializer),
    )


@pytest.mark.django_db
class TestCreateModelFactoryRoundTrip:
    def test_post_returns_201_and_persists(self) -> None:
        request = APIRequestFactory().post("/authors/", {"name": "Ada"}, format="json")
        response = _CreateAuthorView.as_view()(request)
        assert response.status_code == 201
        response.render()
        assert response.data == {"id": Author.objects.get().pk, "name": "Ada"}
