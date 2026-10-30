"""``@service_action`` serving a kernel ``ServiceSpec``.

The decorated action dispatches through the standalone mutation views' own
edge (``dispatch_mutation_for_spec``), and the spec is asked at decoration what
``validate_mutation_view_spec`` asks of a standalone view's, so each test fails
against a tree whose decorator reads drfs fields off the spec.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django_service_specs import (
    AdditionalInputRequired,
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter
from rest_framework.test import APIRequestFactory
from rest_framework.views import exception_handler
from rest_framework.viewsets import GenericViewSet, ViewSet

from django_spec_rest import ActionSerializerResolver, ServiceViewSet, service_action
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

    def test_the_viewset_s_response_finalizer_runs(self) -> None:
        def finalize(*, response: Response) -> Response:
            response["X-Done"] = "yes"
            return response

        viewset = _viewset(
            _collection(), detail=False, base=ServiceViewSet, response_finalizer=finalize
        )
        assert _post(viewset, {"note": "go"})["X-Done"] == "yes"

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

    def test_a_nested_selector_s_permissions_are_refused(self) -> None:
        nested = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, pk: None,
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
            permissions=_OPEN,
        )
        with pytest.raises(ImproperlyConfigured, match="@service_action .*declares permissions"):
            _viewset(_detail(instance_selector_spec=nested), detail=True)

    def test_a_collection_action_with_no_target_is_accepted(self) -> None:
        assert _viewset(_collection(), detail=False).act.detail is False

    def test_a_keyword_the_viewset_s_hook_fills_is_not_refused(self) -> None:
        """The decorated class is unknown, so a keyword nothing the spec
        declares fills may be its hook's: ``check_seeds`` is not asked."""

        def announce(*, data: dict[str, Any], tag: str) -> None: ...

        assert _viewset(_collection(service=announce), detail=False).act.detail is False


class TestRouting:
    """What the decorator forwards to DRF's ``@action`` is what the router routes."""

    def test_methods_url_path_and_url_name_reach_the_route(self) -> None:
        @service_action(
            _collection(), detail=False, methods=["put"], url_path="say-it", url_name="say"
        )
        def announce(self: Any, request: Any) -> None:
            """Stubbed: the decorator serves the spec."""

        viewset = type("_ViewSet", (GenericViewSet,), {"announce": announce})
        router = SimpleRouter()
        router.register("authors", viewset, basename="authors")

        (route,) = [url for url in router.urls if url.name == "authors-say"]
        assert route.pattern.regex.pattern == "^authors/say-it/$"
        response = route.callback(factory.put("/", {"note": "hi"}, format="json"))
        assert response.status_code == 200, response.data
        assert response.data["name"] == "hi"

    def test_with_none_given_drf_s_defaults_route_it(self) -> None:
        """No ``methods``, ``url_path`` or ``url_name``: DRF's ``@action`` routes
        ``GET`` under the method's own name."""

        @service_action(_collection(validator=None, service=lambda: None), detail=False)
        def ping(self: Any, request: Any) -> None:
            """Stubbed: the decorator serves the spec."""

        viewset = type("_ViewSet", (GenericViewSet,), {"ping": ping})
        router = SimpleRouter()
        router.register("authors", viewset, basename="authors")

        (route,) = [url for url in router.urls if url.name == "authors-ping"]
        assert route.pattern.regex.pattern == "^authors/ping/$"
        assert route.callback(factory.get("/")).status_code == 204


# ``AdditionalInputRequired`` carries a JSON Schema DRF would stringify leaf by
# leaf: ``False`` as ``"False"``, ``3`` as ``"3"``.
_PURGE_SCHEMA: dict[str, Any] = {
    "confirmed": {"type": "boolean", "default": False},
    "batches": {"type": "integer", "minimum": 1, "maximum": 3},
    "mode": {"enum": ["soft", None]},
}


def _purge() -> None:
    raise AdditionalInputRequired("Confirm the purge.", schema=_PURGE_SCHEMA)


def _purging(*bases: type) -> type:
    @service_action(
        ServiceSpec(service=_purge, permissions=_OPEN, atomic=False),
        detail=False,
        methods=["post"],
    )
    def purge(self: Any, request: Any) -> None:
        """Stubbed: the decorator serves the spec."""

    return type("_Purging", bases, {"queryset": Author.objects.all(), "purge": purge})


# Every way a ``@service_action`` can sit on a viewset, keyed by its bases: DRF's
# own two, and this package's bases on either side of ``GenericViewSet``, where
# ``APIView.handle_exception`` shadows the package's restore.
_BASES: dict[str, tuple[type, ...]] = {
    "GenericViewSet": (GenericViewSet,),
    "ViewSet": (ViewSet,),
    "ServiceViewSet": (ServiceViewSet,),
    "ActionSerializerResolver, GenericViewSet": (ActionSerializerResolver, GenericViewSet),
    "GenericViewSet, ActionSerializerResolver": (GenericViewSet, ActionSerializerResolver),
}

_seen: list[Exception] = []


def _recording(exc: Exception, context: dict[str, Any]) -> Response | None:
    """DRF's own handler, keeping hold of the exception it was given."""
    _seen.append(exc)
    return exception_handler(exc, context)


def _declining(exc: Exception, context: dict[str, Any]) -> Response | None:
    _seen.append(exc)
    return None


def _handled_by(name: str) -> Any:
    return override_settings(
        REST_FRAMEWORK={**settings.REST_FRAMEWORK, "EXCEPTION_HANDLER": f"{__name__}.{name}"}
    )


def _purge_through(viewset: type) -> Any:
    response = viewset.as_view({"post": "purge"})(factory.post("/", {}, format="json"))
    response.render()
    return response


@pytest.mark.parametrize("bases", list(_BASES))
def test_service_action_serves_the_schema_as_raised_on_any_viewset(bases: str) -> None:
    """Read off the rendered bytes: the boolean default arrives as ``false`` and
    the bound as ``3``. The configured handler runs once and sees DRF's
    ``ErrorDetail`` leaves. ``GenericViewSet``, ``ViewSet`` and
    ``GenericViewSet, ActionSerializerResolver`` reach no restore of the
    package's bases, so they serve the strings without the decorator's own."""
    _seen.clear()
    with _handled_by("_recording"):
        response = _purge_through(_purging(*_BASES[bases]))

    assert response.status_code == 422
    assert json.loads(response.content) == {"detail": "Confirm the purge.", "schema": _PURGE_SCHEMA}
    assert len(_seen) == 1
    leaf = _seen[0].detail["schema"]["confirmed"]["default"]  # ty: ignore[unresolved-attribute]
    assert isinstance(leaf, ErrorDetail)
    assert leaf == "False"


@pytest.mark.parametrize("bases", list(_BASES))
def test_a_handler_declining_the_error_runs_once_on_any_viewset(bases: str) -> None:
    """A handler answering ``None`` declines the error, so DRF raises it, once."""
    _seen.clear()
    with _handled_by("_declining"), pytest.raises(Exception, match="Confirm the purge."):
        _purge_through(_purging(*_BASES[bases]))

    assert len(_seen) == 1


class _Redacting:
    """A viewset's own ``handle_exception``, rewriting the body it is handed."""

    def handle_exception(self, exc: Exception) -> Response:
        response = super().handle_exception(exc)  # ty: ignore[unresolved-attribute]
        response.data["schema"] = {"redacted": True}
        return response


@pytest.mark.parametrize("bases", list(_BASES))
def test_an_overriding_handle_exception_has_the_last_word_on_every_route(bases: str) -> None:
    """The restore runs inside the handler, beneath any ``handle_exception``
    override, so what the override writes is what the client gets."""
    response = _purge_through(_purging(_Redacting, *_BASES[bases]))

    assert response.status_code == 422
    assert json.loads(response.content) == {
        "detail": "Confirm the purge.",
        "schema": {"redacted": True},
    }


def _signing(exc: Exception, context: dict[str, Any]) -> Response | None:
    """DRF's handler, with a key of its own added to the body."""
    response = exception_handler(exc, context)
    assert response is not None
    response.data["handled_by"] = "the viewset"
    return response


class _OwnHandler:
    """A viewset choosing its own exception handler over ``EXCEPTION_HANDLER``."""

    def get_exception_handler(self) -> Any:
        return _signing


@pytest.mark.parametrize("bases", list(_BASES))
def test_a_viewsets_own_exception_handler_still_answers_on_any_viewset(bases: str) -> None:
    """The handler is asked through the view's own ``get_exception_handler``, as
    DRF asks it, and the schema is restored on what that handler built."""
    response = _purge_through(_purging(_OwnHandler, *_BASES[bases]))

    assert response.status_code == 422
    assert json.loads(response.content) == {
        "detail": "Confirm the purge.",
        "schema": _PURGE_SCHEMA,
        "handled_by": "the viewset",
    }
