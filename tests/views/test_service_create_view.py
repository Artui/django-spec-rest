"""``ServiceCreateView`` over a kernel spec, and the view's hook chains on it.

The view's hooks are its own layers, beneath the spec's providers, which the
kernel calls itself: ``get_service_kwargs`` is ``dispatch``'s ``extra_kwargs``,
``get_input_data`` goes into the arguments over the body, the serializer
context hooks reach the spec's ``SerializerValidator`` and
``SerializerPresenter``, and ``get_progress_reporter`` is ``dispatch``'s
``progress``.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User
from django_service_specs import (
    Parameter,
    Parameters,
    ProgressReporter,
    SelectorKind,
    SelectorSpec,
    ServiceError,
    ServiceSpec,
    ServiceValidationError,
    UnknownArguments,
    Unrestricted,
)
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest import ServiceCreateView
from django_spec_rest.dispatch import kernel_edge
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_PRESENTER = SerializerPresenter(AuthorSerializer)


class _NameIn(serializers.Serializer):
    name = serializers.CharField()


class _NestedIn(serializers.Serializer):
    name = serializers.CharField()
    parent_id = serializers.IntegerField()


def _create_author(*, data: dict[str, Any]) -> Author:
    return Author.objects.create(name=data["name"])


async def _create_author_async(*, data: dict[str, Any]) -> Author:
    return await Author.objects.acreate(name=data["name"])


def _spec(service: Any = _create_author, **seats: Any) -> ServiceSpec:
    seats.setdefault("validator", SerializerValidator(_NameIn))
    return ServiceSpec(service=service, permissions=_OPEN, **seats)


def _view(spec: ServiceSpec, **attrs: Any) -> Any:
    return type("_View", (ServiceCreateView,), {"spec": spec, **attrs}).as_view()


def _post(view: Any, body: Any, **kwargs: Any) -> Any:
    return view(factory.post("/", body, format="json"), **kwargs)


class TestServiceCreateView:
    def test_creates_and_returns_201(self) -> None:
        response = _post(_view(_spec(presenter=_PRESENTER)), {"name": "Ada"})
        assert response.status_code == 201
        assert response.data["name"] == "Ada"
        assert Author.objects.filter(name="Ada").exists()

    def test_validation_error_returns_400(self) -> None:
        response = _post(_view(_spec(presenter=_PRESENTER)), {})
        assert response.status_code == 400
        assert response.data["name"][0].code == "required"

    def test_async_service_dispatched(self) -> None:
        response = _post(_view(_spec(_create_author_async, presenter=_PRESENTER)), {"name": "Al"})
        assert response.status_code == 201
        assert response.data["name"] == "Al"

    def test_no_validator_accepts_an_empty_body(self) -> None:
        spec = ServiceSpec(service=lambda: {"triggered": True}, permissions=_OPEN)
        response = _post(_view(spec), {})
        assert response.status_code == 201
        assert response.data == {"triggered": True}

    def test_a_create_is_handed_no_target(self) -> None:
        """A create resolves nothing, so the view's object permissions are
        asked of no row, and the call runs."""

        class _DenyObject(BasePermission):
            def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
                return False

        view = _view(_spec(presenter=_PRESENTER), permission_classes=[_DenyObject])
        assert _post(view, {"name": "Ada"}).status_code == 201

    def test_service_validation_error_maps_to_400(self) -> None:
        def boom(*, data: dict[str, Any]) -> None:
            raise ServiceValidationError({"name": ["taken"]})

        response = _post(_view(_spec(boom, atomic=False)), {"name": "Ada"})
        assert response.status_code == 400
        assert response.data == {"name": ["taken"]}

    def test_service_error_maps_to_422(self) -> None:
        def boom(*, data: dict[str, Any]) -> None:
            raise ServiceError("nope")

        assert _post(_view(_spec(boom, atomic=False)), {"name": "Ada"}).status_code == 422

    def test_missing_spec_raises_not_implemented(self) -> None:
        class _Empty(ServiceCreateView): ...

        with pytest.raises(NotImplementedError, match="requires a `spec`"):
            _Empty.as_view()(factory.post("/", {}, format="json"))

    @pytest.mark.parametrize("presenter", [None, _PRESENTER])
    def test_service_returning_none_renders_204(self, presenter: Any) -> None:
        response = _post(_view(_spec(lambda *, data: None, presenter=presenter)), {"name": "x"})
        assert response.status_code == 204
        assert response.data is None

    def test_output_selector_returning_none_renders_204_over_a_presenter(self) -> None:
        spec = _spec(
            output_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, result: None,
                allow_none=True,
                permissions=_OPEN,
                presenter=_PRESENTER,
            )
        )
        response = _post(_view(spec), {"name": "Ada"})
        assert response.status_code == 204
        assert Author.objects.filter(name="Ada").exists()

    def test_output_selector_invoked(self) -> None:
        other = Author.objects.create(name="other")
        spec = _spec(
            output_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, result: other,
                permissions=_OPEN,
                presenter=_PRESENTER,
            )
        )
        assert _post(_view(spec), {"name": "Ada"}).data == {"id": other.pk, "name": "other"}

    def test_a_view_success_status_overrides_the_create_s_201(self) -> None:
        response = _post(_view(_spec(presenter=_PRESENTER), success_status=202), {"name": "Ada"})
        assert response.status_code == 202

    def test_the_spec_s_kwargs_provider_reaches_the_service(self) -> None:
        def fn(*, data: dict[str, Any], tenant_id: int = 0) -> dict[str, int]:
            return {"tenant_id": tenant_id}

        spec = _spec(fn, kwargs=lambda *, view: {"tenant_id": view.kwargs["tenant"]})
        assert _post(_view(spec), {"name": "Ada"}, tenant=99).data == {"tenant_id": 99}

    def test_the_service_receives_the_view_and_request_it_declares(self) -> None:
        captured: dict[str, Any] = {}

        def fn(*, data: dict[str, Any], view: Any, request: Any) -> None:
            captured.update(view=view, request=request)

        view = _view(_spec(fn))
        _post(view, {"name": "Bob"})
        assert isinstance(captured["view"], ServiceCreateView)
        assert captured["request"] is captured["view"].request


class TestTheViewsHookChains:
    def test_get_service_kwargs_reaches_the_service(self) -> None:
        def fn(*, tenant: str = "unset") -> dict[str, str]:
            return {"tenant": tenant}

        spec = ServiceSpec(service=fn, permissions=_OPEN, atomic=False)
        view = _view(spec, get_service_kwargs=lambda self: {"tenant": "acme"})
        assert _post(view, {}).data == {"tenant": "acme"}

    def test_the_spec_s_kwargs_provider_outranks_get_service_kwargs(self) -> None:
        def fn(*, tenant: str = "unset") -> dict[str, str]:
            return {"tenant": tenant}

        spec = ServiceSpec(
            service=fn, permissions=_OPEN, kwargs=lambda: {"tenant": "spec"}, atomic=False
        )
        view = _view(spec, get_service_kwargs=lambda self: {"tenant": "view"})
        assert _post(view, {}).data == {"tenant": "spec"}

    def test_a_get_service_kwargs_value_named_like_a_field_pins_it(self) -> None:
        """The serializer validates the server's value, never the client's, as
        it did on drfs, and the service is handed the validated one."""

        def fn(*, data: dict[str, Any], name: str) -> dict[str, Any]:
            return {"data": dict(data), "name": name}

        view = _view(_spec(fn), get_service_kwargs=lambda self: {"name": "pinned"})
        response = _post(view, {"name": "client"})
        assert response.status_code == 201
        assert response.data == {"data": {"name": "pinned"}, "name": "pinned"}

    def test_a_get_service_kwargs_value_named_like_a_seed_field_pins_it(self) -> None:
        class _Owned(serializers.Serializer):
            user = serializers.IntegerField()

        view = _view(
            _spec(lambda *, data: dict(data), validator=SerializerValidator(_Owned)),
            get_service_kwargs=lambda self: {"user": 7},
        )
        assert _post(view, {"user": 1}).data == {"user": 7}

    def test_a_get_service_kwargs_value_named_like_a_spec_read_pins_it(self) -> None:
        """A hook's key naming one of the spec's own reads, not a Validator
        field, is pinned into the arguments too: the kernel refuses an overlay
        key naming a parameter, so left in the overlay it would be a 500."""
        seen: dict[str, Any] = {}
        spec = ServiceSpec(
            service=lambda *, note: seen.update(note=note),
            permissions=_OPEN,
            reads=Parameters.of(Parameter("note", "string")),
            atomic=False,
        )
        view = _view(spec, get_service_kwargs=lambda self: {"note": "server"})
        response = _post(view, {"note": "client"})
        assert response.status_code == 204
        assert seen == {"note": "server"}

    def test_get_input_data_outranks_a_pinning_get_service_kwargs(self) -> None:
        view = _view(
            _spec(lambda *, data: dict(data)),
            get_service_kwargs=lambda self: {"name": "kwargs"},
            get_input_data=lambda self, request: {"name": "input"},
        )
        assert _post(view, {"name": "client"}).data == {"name": "input"}

    def test_get_input_data_reaches_the_validator_over_the_body(self) -> None:
        def fn(*, data: dict[str, Any]) -> dict[str, Any]:
            return dict(data)

        view = _view(
            _spec(fn, validator=SerializerValidator(_NestedIn)),
            get_input_data=lambda self, request: {"parent_id": int(self.kwargs["parent_id"])},
        )
        response = _post(view, {"name": "Ada", "parent_id": 1}, parent_id=11)
        assert response.status_code == 201
        assert response.data == {"name": "Ada", "parent_id": 11}

    def test_input_data_three_tier_chain(self) -> None:
        """The spec's ``input_data`` over the view's, the view's over the body."""

        def fn(*, data: dict[str, Any]) -> dict[str, Any]:
            return dict(data)

        spec = _spec(
            fn,
            validator=SerializerValidator(_NestedIn),
            input_data=lambda *, view: {"name": "from-spec"},
        )
        view = _view(spec, get_input_data=lambda self, request: {"name": "view", "parent_id": 5})
        response = _post(view, {"name": "body", "parent_id": 1})
        assert response.data == {"name": "from-spec", "parent_id": 5}

    @pytest.mark.parametrize(
        ("policy", "status"), [(UnknownArguments.REJECT, 400), (UnknownArguments.IGNORE, 201)]
    )
    def test_a_get_input_data_key_naming_no_field_is_the_policy_s(
        self, monkeypatch: pytest.MonkeyPatch, policy: UnknownArguments, status: int
    ) -> None:
        """A view's key is an argument like the client's, so the unknown-argument
        policy answers it: refused under ``REJECT``, dropped under ``IGNORE``."""
        monkeypatch.setattr(kernel_edge, "UNKNOWN_ARGUMENTS", policy)
        view = _view(_spec(presenter=_PRESENTER), get_input_data=lambda self, request: {"x": 1})
        response = _post(view, {"name": "Ada"})
        assert response.status_code == status
        if status == 400:
            assert "Unknown argument." in str(response.data["x"])

    def test_the_input_serializer_context_hook_reaches_the_validator(self) -> None:
        class _Tenant(serializers.Serializer):
            name = serializers.CharField()

            def validate_name(self, value: str) -> str:
                return f"{self.context['tenant']}:{value}"

        view = _view(
            _spec(validator=SerializerValidator(_Tenant), presenter=_PRESENTER),
            get_input_serializer_context=lambda self: {
                **self.get_serializer_context(),
                "tenant": "t",
            },
        )
        assert _post(view, {"name": "Ada"}).data["name"] == "t:Ada"

    def test_the_output_serializer_context_hook_reaches_the_presenter(self) -> None:
        class _Tagged(serializers.Serializer):
            name = serializers.SerializerMethodField()

            def get_name(self, obj: Author) -> str:
                return f"{self.context['tag']}:{obj.name}"

        view = _view(
            _spec(presenter=SerializerPresenter(_Tagged)),
            get_output_serializer_context=lambda self: {
                **self.get_serializer_context(),
                "tag": "o",
            },
        )
        assert _post(view, {"name": "Ada"}).data == {"name": "o:Ada"}

    def test_the_view_s_progress_reporter_hears_the_service(self) -> None:
        heard: list[Any] = []

        class _Sink(ProgressReporter):
            def report(self, *args: Any, **kwargs: Any) -> None:
                heard.append(kwargs or args)

        def fn(*, progress: Any) -> None:
            progress.report(current=1, total=2)

        spec = ServiceSpec(service=fn, permissions=_OPEN, atomic=False)
        view = _view(spec, get_progress_reporter=lambda self: _Sink())
        assert _post(view, {}).status_code == 204
        assert heard


class _Noted(serializers.Serializer):
    """A ``note`` field the serializer declares only where its context says so."""

    name = serializers.CharField()

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        request = self.context["request"]
        if request.user.is_staff or self.context.get("noted"):
            fields["note"] = serializers.CharField()
        return fields


class TestTheDescription:
    """A kernel spec's input serializer is described with the call's context."""

    def _noted(self, received: dict[str, Any], **validator: Any) -> ServiceSpec:
        return _spec(
            service=lambda *, data: received.update(data),
            validator=SerializerValidator(_Noted, **validator),
        )

    def test_a_request_scoped_serializer_declares_the_fields_the_call_validates(self) -> None:
        received: dict[str, Any] = {}
        request = factory.post("/", {"name": "Ada", "note": "kept"}, format="json")
        force_authenticate(request, user=User.objects.create(username="staff", is_staff=True))
        response = _view(self._noted(received))(request)
        assert response.status_code == 204, response.data
        assert received == {"name": "Ada", "note": "kept"}

    def test_the_view_s_input_layer_reaches_the_description(self) -> None:
        received: dict[str, Any] = {}
        view = _view(
            self._noted(received),
            get_input_serializer_context=lambda self: {
                **self.get_serializer_context(),
                "noted": True,
            },
        )
        assert _post(view, {"name": "Ada", "note": "kept"}).status_code == 204
        assert received == {"name": "Ada", "note": "kept"}

    def test_the_validator_s_own_context_reaches_the_description(self) -> None:
        received: dict[str, Any] = {}
        spec = self._noted(received, serializer_context=lambda *, request: {"noted": True})
        assert _post(_view(spec), {"name": "Ada", "note": "kept"}).status_code == 204
        assert received == {"name": "Ada", "note": "kept"}

    def test_a_serializer_its_description_cannot_build_raises_as_it_is(self) -> None:
        class _Tenanted(serializers.Serializer):
            def get_fields(self) -> dict[str, serializers.Field]:
                return {self.context["tenant"]: serializers.CharField()}

        with pytest.raises(KeyError, match="tenant"):
            _post(_view(_spec(validator=SerializerValidator(_Tenanted))), {})
