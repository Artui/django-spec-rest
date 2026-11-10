from __future__ import annotations

import pytest
from django_service_specs import SelectorKind, SelectorSpec, ServiceSpec, Unrestricted
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import ActionSerializerResolver
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer, PostSerializer

_OPEN = (Unrestricted(),)


class _Vs(ActionSerializerResolver, GenericViewSet):
    queryset = Author.objects.all()
    serializer_class = AuthorSerializer
    action_specs = {
        "list": SelectorSpec(
            kind=SelectorKind.LIST,
            selector=lambda: Author.objects.all(),
            permissions=_OPEN,
            presenter=SerializerPresenter(PostSerializer),
        ),
        "create": ServiceSpec(
            service=lambda: None, permissions=_OPEN, presenter=SerializerPresenter(PostSerializer)
        ),
    }


@pytest.mark.parametrize("action", ["list", "create", "partial_update", None])
def test_a_kernel_entry_resolves_to_the_view_s_serializer_class(action: str | None) -> None:
    vs = _Vs()
    vs.action = action
    assert vs.get_serializer_class() is AuthorSerializer


def test_with_no_serializer_class_drf_s_assertion_stands() -> None:
    vs = _Vs()
    vs.serializer_class = None
    vs.action = "list"
    with pytest.raises(AssertionError):
        vs.get_serializer_class()
