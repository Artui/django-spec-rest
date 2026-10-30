"""``base_serializer_context``: DRF's baseline context, on and off the HTTP path, for a kernel spec."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django_service_specs import SelectorKind, SelectorSpec, Unrestricted
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.present import present
from rest_framework import serializers

from django_spec_rest.service_specs.base_serializer_context import base_serializer_context
from django_spec_rest.service_specs.build_offline_context import build_offline_context
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Post


class _ViewWithContext:
    """Stands in for a DRF ``GenericAPIView`` (which owns the hook)."""

    def get_serializer_context(self) -> dict[str, Any]:
        return {"request": "HTTP-REQ", "format": "json", "view": self, "extra": 1}


class TestBaseSerializerContext:
    def test_synthesizes_drf_shape_without_a_view_hook(self) -> None:
        view = object()
        assert base_serializer_context(view=view, request="REQ") == {
            "request": "REQ",
            "format": None,
            "view": view,
        }

    def test_keys_present_even_when_nothing_was_passed(self) -> None:
        # The point of the baseline: ``self.context["request"]`` never KeyErrors.
        assert base_serializer_context(view=None, request=None) == {
            "request": None,
            "format": None,
            "view": None,
        }

    def test_view_hook_wins_when_present(self) -> None:
        view = _ViewWithContext()
        assert base_serializer_context(view=view, request="IGNORED") == {
            "request": "HTTP-REQ",
            "format": "json",
            "view": view,
            "extra": 1,
        }

    def test_result_is_a_fresh_dict_the_caller_may_mutate(self) -> None:
        view = _ViewWithContext()
        context = base_serializer_context(view=view, request=None)
        context["request"] = "OVERRIDDEN"
        assert view.get_serializer_context()["request"] == "HTTP-REQ"

    def test_non_callable_attribute_is_not_mistaken_for_the_hook(self) -> None:
        class _Odd:
            get_serializer_context = "not a method"

        view = _Odd()
        assert base_serializer_context(view=view, request="REQ")["request"] == "REQ"

    def test_offline_context_pair_carries_the_synthetic_request(self) -> None:
        offline = build_offline_context(user="U")
        context = base_serializer_context(view=offline.view, request=offline.request)
        assert context["request"] is offline.request
        assert context["request"].user == "U"
        assert context["view"] is offline.view
        assert context["format"] is None


class _FileFieldShapedSerializer(serializers.Serializer):
    """Mirrors DRF's ``FileField.to_representation`` branch for a URL."""

    url = serializers.SerializerMethodField()

    def get_url(self, _: object) -> str:
        request = self.context.get("request", None)
        if request is not None:
            return request.build_absolute_uri("/media/doc.pdf")
        return "/media/doc.pdf"


@pytest.mark.django_db
class TestFileFieldsOffHttp:
    """A request in the context must not be worse than none.

    A synthesized request with an empty ``META`` would raise
    ``KeyError: 'SERVER_NAME'`` from ``build_absolute_uri``, so a serializer
    with a ``FileField`` would break on a path that renders a relative URL with
    no request at all. A transport carries the offline pair in the call's
    context, as one with no DRF view of its own does.
    """

    def _render(self, host: str | None) -> Any:
        Post.objects.create(title="a")
        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=lambda: Post.objects.all(),
            permissions=(Unrestricted(),),
            presenter=SerializerPresenter(_FileFieldShapedSerializer, value_keyword=None),
        )
        offline = build_offline_context(user=None, host=host)
        result = dispatch(
            spec,
            principal=AnonymousUser(),
            arguments={},
            call_context={"request": offline.request, "view": offline.view},
        )
        return present(spec, result)

    def test_without_a_host_the_url_is_relative(self) -> None:
        assert [row["url"] for row in self._render(None)] == ["/media/doc.pdf"]

    def test_with_a_host_the_url_is_absolute(self) -> None:
        assert [row["url"] for row in self._render("https://files.example.com")] == [
            "https://files.example.com/media/doc.pdf"
        ]
