"""A viewset's ``success_status`` and ``response_finalizer`` per action.

A kernel spec declares no HTTP answer, so the viewset does, and one action may
answer differently from another without a callable switching on
``view.action``: ``@service_action(..., success_status=..., response_finalizer=...)``
for a decorated action, and a ``get_<action>_success_status`` /
``get_<action>_response_finalizer`` hook for an ``action_specs`` entry. Most
specific first: the decorator's value, then the hook, then the viewset's own,
then the action's default.

Every viewset carrying a decorator keyword is built inside its test, so a tree
whose ``@service_action`` takes no such keyword fails that test, not the
module's import.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from django_spec_rest import ServiceViewSet, service_action
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_BY_PK = Parameters.of(Parameter("pk", "integer", required=True))


class _NameIn(serializers.Serializer):
    name = serializers.CharField(max_length=20)


def _create_author(*, data: dict[str, Any]) -> Author:
    return Author.objects.create(name=data["name"])


def _rename(*, instance: Author, data: dict[str, Any]) -> Author:
    instance.name = data["name"]
    instance.save(update_fields=["name"])
    return instance


def _delete(*, instance: Author) -> None:
    instance.delete()


def _target() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
        reads=_BY_PK,
    )


def _create() -> ServiceSpec:
    return ServiceSpec(
        service=_create_author,
        permissions=_OPEN,
        validator=SerializerValidator(_NameIn),
        presenter=SerializerPresenter(AuthorSerializer),
    )


def _update() -> ServiceSpec:
    return ServiceSpec(
        service=_rename,
        permissions=_OPEN,
        validator=SerializerValidator(_NameIn),
        presenter=SerializerPresenter(AuthorSerializer),
        instance_selector_spec=_target(),
    )


def _destroy() -> ServiceSpec:
    return ServiceSpec(service=_delete, permissions=_OPEN, instance_selector_spec=_target())


def _header(name: str) -> Any:
    def finalize(*, response: Response) -> None:
        response["X-Answer"] = name

    return finalize


def _call(viewset: Any, method: str, action: str, body: Any = None, **kwargs: Any) -> Response:
    view = viewset.as_view({method: action})
    return view(getattr(factory, method)("/", body, format="json"), **kwargs)


def _stub(self: Any, request: Any) -> None:
    """Stubbed: the decorator serves the spec."""


def _decorated_viewset(**attrs: Any) -> type:
    """Two decorated actions answering differently, beside one taking the viewset's own."""

    @service_action(
        _create(), methods=["post"], success_status=201, response_finalizer=_header("enrol")
    )
    def enrol(self: Any, request: Any) -> None:
        """Stubbed: the decorator serves the spec."""

    @service_action(
        _destroy(),
        detail=True,
        methods=["post"],
        success_status=204,
        response_finalizer=_header("retire"),
    )
    def retire(self: Any, request: Any, pk: Any = None) -> None:
        """Stubbed: the decorator serves the spec."""

    @service_action(_create(), methods=["post"])
    def note(self: Any, request: Any) -> None:
        """Stubbed: the decorator serves the spec."""

    body = {
        "queryset": Author.objects.all(),
        "enrol": enrol,
        "retire": retire,
        "note": note,
        "success_status": 202,
        "response_finalizer": _header("viewset"),
        **attrs,
    }
    return type("_ViewSet", (ServiceViewSet,), body)


class TestADecoratedActionAnswersForItself:
    def test_two_actions_answer_different_statuses_and_finalizers(self) -> None:
        viewset = _decorated_viewset()
        enrolled = _call(viewset, "post", "enrol", {"name": "Ada"})
        retired = _call(viewset, "post", "retire", pk=Author.objects.create(name="Bo").pk)
        assert (enrolled.status_code, enrolled["X-Answer"]) == (201, "enrol")
        assert (retired.status_code, retired["X-Answer"]) == (204, "retire")

    def test_an_action_naming_neither_takes_the_viewset_s(self) -> None:
        response = _call(_decorated_viewset(), "post", "note", {"name": "Ada"})
        assert (response.status_code, response["X-Answer"]) == (202, "viewset")

    def test_it_outranks_the_viewset_s_keyword_to_as_view(self) -> None:
        view = _decorated_viewset().as_view({"post": "enrol"}, success_status=299)
        response = view(factory.post("/", {"name": "Ada"}, format="json"))
        assert response.status_code == 201

    def test_a_status_the_view_cannot_resolve_is_refused_at_decoration(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="success_status"):
            service_action(_create(), success_status="created")(_stub)

    def test_a_finalizer_the_view_cannot_call_is_refused_at_decoration(self) -> None:
        def needs_tenant(*, tenant: Any) -> None: ...

        with pytest.raises(ImproperlyConfigured, match="response_finalizer"):
            service_action(_create(), response_finalizer=needs_tenant)(_stub)


def _hooked_viewset(**attrs: Any) -> type:
    """``action_specs`` actions answering differently through their per-action hooks."""
    body = {
        "queryset": Author.objects.all(),
        "action_specs": {"create": _create(), "update": _update(), "destroy": _destroy()},
        "success_status": 202,
        "response_finalizer": _header("viewset"),
        **attrs,
    }
    return type("_ViewSet", (ServiceViewSet,), body)


class _Hooks:
    """Per-action hooks: a method is the callable itself, and an ``int`` is the status."""

    def get_create_success_status(self, *, result: Author) -> int:
        return 201 if result.name else 200

    def get_create_response_finalizer(self, *, response: Response, view: Any) -> None:
        response["X-Answer"] = f"create:{view.action}"

    get_destroy_success_status = 200


class TestAnActionSpecsEntryAnswersThroughItsHook:
    def test_two_actions_answer_different_statuses_and_finalizers(self) -> None:
        viewset = type("_Hooked", (_Hooks, _hooked_viewset()), {})
        created = _call(viewset, "post", "create", {"name": "Ada"})
        destroyed = _call(viewset, "delete", "destroy", pk=Author.objects.create(name="Bo").pk)
        assert (created.status_code, created["X-Answer"]) == (201, "create:create")
        # A status set answers an empty body too, and the viewset's finalizer stands.
        assert (destroyed.status_code, destroyed["X-Answer"]) == (200, "viewset")

    def test_an_action_with_no_hook_takes_the_viewset_s(self) -> None:
        viewset = type("_Hooked", (_Hooks, _hooked_viewset()), {})
        author = Author.objects.create(name="Bo")
        response = _call(viewset, "put", "update", {"name": "Cy"}, pk=author.pk)
        assert (response.status_code, response["X-Answer"]) == (202, "viewset")

    def test_partial_update_reads_its_own_name_not_update_s(self) -> None:
        # The per-action hooks are spelled with the action DRF names, as
        # ``get_<action>_service_kwargs`` is: a ``PATCH`` is ``partial_update``.
        viewset = _hooked_viewset(
            get_update_success_status=201, get_partial_update_success_status=203
        )
        author = Author.objects.create(name="Bo")
        put = _call(viewset, "put", "update", {"name": "Cy"}, pk=author.pk)
        patch = _call(viewset, "patch", "partial_update", {"name": "Di"}, pk=author.pk)
        assert (put.status_code, patch.status_code) == (201, 203)

    def test_the_viewset_wide_value_is_unchanged_without_hooks(self) -> None:
        viewset = _hooked_viewset()
        created = _call(viewset, "post", "create", {"name": "Ada"})
        assert (created.status_code, created["X-Answer"]) == (202, "viewset")


class TestTheMountedChecksReadThePerActionValue:
    @pytest.mark.parametrize("action", ["create", "update", "destroy"])
    def test_a_status_hook_the_view_cannot_resolve_is_refused(self, action: str) -> None:
        def hook(self: Any, *, tenant: Any) -> int:
            return 200

        viewset = _hooked_viewset(**{f"get_{action}_success_status": hook})
        with pytest.raises(ImproperlyConfigured, match=rf"\[{action!r}\].*success_status"):
            viewset.as_view({"post": action})

    @pytest.mark.parametrize("action", ["create", "update", "destroy"])
    def test_a_finalizer_hook_the_view_cannot_call_is_refused(self, action: str) -> None:
        def hook(self: Any, response: Response, /) -> None: ...

        viewset = _hooked_viewset(**{f"get_{action}_response_finalizer": hook})
        with pytest.raises(ImproperlyConfigured, match=rf"\[{action!r}\].*response_finalizer"):
            viewset.as_view({"post": action})

    def test_a_hook_s_own_self_is_not_a_key_it_requires(self) -> None:
        viewset = type("_Hooked", (_Hooks, _hooked_viewset()), {})
        assert viewset.as_view({"post": "create"}) is not None

    def test_a_status_that_is_neither_an_int_nor_a_callable_is_refused(self) -> None:
        viewset = _hooked_viewset(get_create_success_status="created")
        with pytest.raises(ImproperlyConfigured, match="must be an int"):
            viewset.as_view({"post": "create"})

    @pytest.mark.parametrize("name", ["success_status", "response_finalizer"])
    def test_a_decorated_action_s_hook_is_asked_too(self, name: str) -> None:
        def hook(self: Any, *, tenant: Any) -> None: ...

        @service_action(_create(), methods=["post"])
        def note(self: Any, request: Any) -> None:
            """Stubbed: the decorator serves the spec."""

        viewset = _hooked_viewset(note=note, **{f"get_note_{name}": hook})
        with pytest.raises(ImproperlyConfigured, match=rf"note.*{name}"):
            viewset.as_view({"post": "note"})

    def test_a_decorated_action_s_valid_hook_answers(self) -> None:
        @service_action(_create(), methods=["post"])
        def note(self: Any, request: Any) -> None:
            """Stubbed: the decorator serves the spec."""

        viewset = _hooked_viewset(note=note, get_note_success_status=201)
        response = _call(viewset, "post", "note", {"name": "Ada"})
        assert response.status_code == 201

    @pytest.mark.parametrize("name", ["success_status", "response_finalizer"])
    def test_a_decorator_value_beside_a_hook_is_refused(self, name: str) -> None:
        # Two values for one action, and no reading of which one answers.
        viewset = _decorated_viewset(**{f"get_enrol_{name}": _header("hook")})
        with pytest.raises(ImproperlyConfigured, match=rf"enrol.*get_enrol_{name}"):
            viewset.as_view({"post": "enrol"})
