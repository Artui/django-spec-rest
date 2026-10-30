"""``@service_action`` serving a kernel ``ServiceSpec``.

The decorated action dispatches through the standalone mutation views' own
edge (``dispatch_mutation_for_spec``), and the spec is asked at decoration what
``validate_mutation_view_spec`` asks of a standalone view's, so each test fails
against a tree whose decorator reads drfs fields off the spec.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import (
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import GenericViewSet, ViewSet

from django_spec_rest import ServiceViewSet, service_action
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.viewsets.utils import resolve_action_spec
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)


class _NoteIn(serializers.Serializer):
    note = serializers.CharField(max_length=10)


class _Deny(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return False


class _DenyAll(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return False


def _by_pk() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
    )


def _rename(*, instance: Author, data: dict[str, Any]) -> Author:
    instance.name = data["note"]
    instance.save(update_fields=["name"])
    return instance


def _announce(*, data: dict[str, Any]) -> Author:
    return Author.objects.create(name=data["note"])


def _detail(**fields: Any) -> ServiceSpec:
    defaults: dict[str, Any] = {
        "service": _rename,
        "permissions": _OPEN,
        "validator": SerializerValidator(_NoteIn),
        "presenter": SerializerPresenter(AuthorSerializer),
        "instance_selector_spec": _by_pk(),
    }
    return ServiceSpec(**{**defaults, **fields})


def _collection(**fields: Any) -> ServiceSpec:
    defaults: dict[str, Any] = {
        "service": _announce,
        "permissions": _OPEN,
        "validator": SerializerValidator(_NoteIn),
        "presenter": SerializerPresenter(AuthorSerializer),
    }
    return ServiceSpec(**{**defaults, **fields})


def _viewset(spec: ServiceSpec, *, detail: bool, base: type = GenericViewSet, **attrs: Any) -> Any:
    @service_action(spec, detail=detail, methods=["post"])
    def act(self: Any, request: Any, pk: Any = None) -> None:
        """Stubbed: the decorator serves the spec."""

    return type("_ViewSet", (base,), {"queryset": Author.objects.all(), "act": act, **attrs})


def _post(viewset: Any, body: Any, **kwargs: Any) -> Response:
    return viewset.as_view({"post": "act"})(factory.post("/", body, format="json"), **kwargs)


class TestADetailAction:
    @pytest.mark.parametrize("base", [GenericViewSet, ViewSet, ServiceViewSet])
    def test_acts_on_its_own_target_on_any_viewset(self, base: type) -> None:
        author = Author.objects.create(name="a")
        response = _post(_viewset(_detail(), detail=True, base=base), {"note": "b"}, pk=author.pk)
        assert response.status_code == 200
        assert response.data == {"id": author.pk, "name": "b"}

    def test_a_missing_row_is_404(self) -> None:
        response = _post(_viewset(_detail(), detail=True), {"note": "b"}, pk=999)
        assert response.status_code == 404

    def test_the_viewset_s_get_object_is_never_asked(self) -> None:
        author = Author.objects.create(name="a")

        def get_object(self: Any) -> Any:
            raise AssertionError("a kernel spec's target is its own selector's")

        viewset = _viewset(_detail(), detail=True, get_object=get_object)
        assert _post(viewset, {"note": "b"}, pk=author.pk).status_code == 200

    def test_a_service_returning_nothing_presents_its_target(self) -> None:
        author = Author.objects.create(name="a")

        def touch(*, instance: Author, data: dict[str, Any]) -> None:
            instance.name = data["note"]
            instance.save(update_fields=["name"])

        response = _post(_viewset(_detail(service=touch), detail=True), {"note": "b"}, pk=author.pk)
        assert response.data == {"id": author.pk, "name": "b"}

    def test_the_view_s_object_permission_is_asked_of_the_target(self) -> None:
        author = Author.objects.create(name="a")

        class _NoRows(BasePermission):
            def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
                return False

        viewset = _viewset(_detail(), detail=True, permission_classes=[_NoRows])
        assert _post(viewset, {"note": "b"}, pk=author.pk).status_code == 403
        assert Author.objects.get().name == "a"


class TestACollectionAction:
    def test_runs_and_presents_with_200(self) -> None:
        response = _post(_viewset(_collection(), detail=False), {"note": "go"})
        assert response.status_code == 200
        assert response.data == {"id": Author.objects.get().pk, "name": "go"}

    def test_an_invalid_body_is_400(self) -> None:
        response = _post(_viewset(_collection(), detail=False), {"note": "x" * 20})
        assert response.status_code == 400
        assert not Author.objects.exists()

    def test_nothing_to_present_is_204(self) -> None:
        def note(*, data: dict[str, Any]) -> None: ...

        spec = _collection(service=note, presenter=None)
        assert _post(_viewset(spec, detail=False), {"note": "go"}).status_code == 204

    def test_the_viewset_s_success_status_answers(self) -> None:
        viewset = _viewset(_collection(), detail=False, base=ServiceViewSet, success_status=202)
        assert _post(viewset, {"note": "go"}).status_code == 202

    def test_a_viewset_hook_fills_a_keyword_at_the_request(self) -> None:
        seen: list[str] = []

        def announce(*, data: dict[str, Any], tag: str) -> Author:
            seen.append(tag)
            return _announce(data=data)

        viewset = _viewset(
            _collection(service=announce),
            detail=False,
            base=ServiceViewSet,
            get_act_service_kwargs=lambda self: {"tag": "hook"},
        )
        assert _post(viewset, {"note": "go"}).status_code == 200
        assert seen == ["hook"]


class TestPermissions:
    def test_the_spec_s_own_checks_refuse(self) -> None:
        viewset = _viewset(_collection(permissions=(_DenyAll(),)), detail=False)
        assert _post(viewset, {"note": "go"}).status_code == 403
        assert not Author.objects.exists()

    @pytest.mark.parametrize("base", [GenericViewSet, ServiceViewSet])
    def test_the_view_s_own_classes_refuse_first(self, base: type) -> None:
        viewset = _viewset(_collection(), detail=False, base=base, permission_classes=[_Deny])
        assert _post(viewset, {"note": "go"}).status_code == 403
        assert not Author.objects.exists()

    def test_no_permission_classes_are_forwarded_to_drf(self) -> None:
        viewset = _viewset(_collection(), detail=False)
        assert "permission_classes" not in viewset.act.kwargs

    def test_the_stamped_spec_is_the_one_the_viewset_resolves(self) -> None:
        spec = _collection()
        view = _viewset(spec, detail=False, base=ServiceViewSet)()
        view.action_specs = {}
        assert resolve_action_spec(view, "act") is spec


class TestAtDecoration:
    def test_a_detail_action_with_no_target_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"@service_action .*no target selector"):
            _viewset(_detail(instance_selector_spec=None), detail=True)

    def test_a_collection_action_with_no_target_is_accepted(self) -> None:
        assert _viewset(_collection(), detail=False).act.detail is False

    def test_a_keyword_the_viewset_s_hook_fills_is_not_refused(self) -> None:
        """The decorated class is unknown, so a keyword nothing the spec
        declares fills may be its hook's: ``check_seeds`` is not asked."""

        def announce(*, data: dict[str, Any], tag: str) -> None: ...

        assert _viewset(_collection(service=announce), detail=False).act.detail is False
