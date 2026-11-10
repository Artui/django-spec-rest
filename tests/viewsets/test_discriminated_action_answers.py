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
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from django_spec_rest.types.discriminated_action import DiscriminatedAction
from django_spec_rest.views.mutation.service_create_view import ServiceCreateView
from django_spec_rest.viewsets.decorators.selector_action import selector_action
from django_spec_rest.viewsets.decorators.service_action import service_action
from django_spec_rest.viewsets.service_viewset import ServiceViewSet
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_STATUS = {"low": 200, "high": 202}


def _status(*, variant: str) -> int:
    return _STATUS[variant]


def _status_by_catch_all(**kwargs: Any) -> int:
    return _STATUS[kwargs["variant"]]


def _finalizer(*, response: Response, variant: str) -> None:
    response["X-Variant"] = variant


def _finalizer_by_catch_all(*, response: Response, **kwargs: Any) -> None:
    response["X-Variant"] = kwargs["variant"]


def _optional_status(*, variant: str = "low") -> int:
    return _STATUS[variant]


def _optional_finalizer(*, response: Response, variant: str = "none") -> None:
    response["X-Variant"] = variant


def _write() -> dict[str, str]:
    return {"done": "yes"}


def _plain() -> ServiceSpec:
    return ServiceSpec(service=_write, permissions=_OPEN)


def _action() -> DiscriminatedAction:
    return DiscriminatedAction(
        lambda *, request: request.query_params.get("to", "low"),
        {"low": _plain(), "high": _plain()},
    )


def _post(view: Any, path: str = "/?to=high", **kwargs: Any) -> Any:
    return view(factory.post(path, {}, format="json"), **kwargs)


def _on_a_row() -> ServiceSpec:
    return ServiceSpec(
        service=lambda *, instance: None,
        permissions=_OPEN,
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
            reads=Parameters.of(Parameter("pk", "integer", required=True)),
        ),
    )


class TestVariantOffered:
    @pytest.mark.parametrize("answer", [_status, _status_by_catch_all, _optional_status])
    def test_a_view_wide_status(self, answer: Any) -> None:
        class _ViewSet(ServiceViewSet):
            success_status = staticmethod(answer)
            action_specs = {"create": _action()}

        view = _ViewSet.as_view({"post": "create"})
        assert _post(view, "/?to=high").status_code == 202
        assert _post(view, "/?to=low").status_code == 200

    @pytest.mark.parametrize("answer", [_finalizer, _finalizer_by_catch_all, _optional_finalizer])
    def test_a_view_wide_finalizer(self, answer: Any) -> None:
        class _ViewSet(ServiceViewSet):
            response_finalizer = staticmethod(answer)
            action_specs = {"create": _action()}

        assert _post(_ViewSet.as_view({"post": "create"}))["X-Variant"] == "high"

    def test_a_per_action_hook(self) -> None:
        class _ViewSet(ServiceViewSet):
            action_specs = {"create": _action()}

            def get_create_success_status(self, *, variant: str) -> int:
                return _STATUS[variant]

            def get_create_response_finalizer(self, *, response: Any, variant: str) -> None:
                response["X-Variant"] = variant

        answer = _post(_ViewSet.as_view({"post": "create"}))
        assert (answer.status_code, answer["X-Variant"]) == (202, "high")

    def test_a_decorator_s_own_values(self) -> None:
        class _ViewSet(ServiceViewSet):
            @service_action(
                _action(), methods=["post"], success_status=_status, response_finalizer=_finalizer
            )
            def run(self, request: Any) -> None:
                """Stubbed."""

        answer = _post(_ViewSet.as_view({"post": "run"}))
        assert (answer.status_code, answer["X-Variant"]) == (202, "high")

    def test_a_decorated_action_s_hook(self) -> None:
        class _ViewSet(ServiceViewSet):
            @service_action(_action(), methods=["post"])
            def run(self, request: Any) -> None:
                """Stubbed."""

            def get_run_success_status(self, *, variant: str) -> int:
                return _STATUS[variant]

            def get_run_response_finalizer(self, *, response: Any, variant: str) -> None:
                response["X-Variant"] = variant

        answer = _post(_ViewSet.as_view({"post": "run"}))
        assert (answer.status_code, answer["X-Variant"]) == (202, "high")

    def test_a_patch_over_the_update_entry_reads_its_own_hook(self) -> None:
        row = Author.objects.create(name="a")
        action = DiscriminatedAction(lambda: "one", {"one": _on_a_row()})

        class _ViewSet(ServiceViewSet):
            action_specs = {"update": action}

            def get_partial_update_success_status(self, *, variant: str) -> int:
                return {"one": 202}[variant]

        view = _ViewSet.as_view({"patch": "partial_update"})
        assert view(factory.patch("/", {}, format="json"), pk=row.pk).status_code == 202

    def test_a_patch_with_its_own_entry_reads_its_own_hook_beside_a_plain_update(self) -> None:
        row = Author.objects.create(name="a")
        action = DiscriminatedAction(lambda: "one", {"one": _on_a_row()})

        class _ViewSet(ServiceViewSet):
            action_specs = {"update": _on_a_row(), "partial_update": action}

            def get_partial_update_success_status(self, *, variant: str) -> int:
                return {"one": 202}[variant]

        view = _ViewSet.as_view({"patch": "partial_update"})
        assert view(factory.patch("/", {}, format="json"), pk=row.pk).status_code == 202

    def test_a_key_of_the_empty_string_is_still_offered(self) -> None:
        action = DiscriminatedAction(lambda: "", {"": _plain()})

        def finalize(*, response: Response, variant: str) -> None:
            response["X-Variant"] = f"[{variant}]"

        class _ViewSet(ServiceViewSet):
            success_status = staticmethod(lambda *, variant: 200 if variant == "" else 500)
            response_finalizer = staticmethod(finalize)
            action_specs = {"create": action}

        answer = _post(_ViewSet.as_view({"post": "create"}), "/")
        assert (answer.status_code, answer["X-Variant"]) == (200, "[]")

    def test_a_key_the_pool_still_lacks_is_refused_beside_it(self) -> None:
        class _ViewSet(ServiceViewSet):
            success_status = staticmethod(lambda *, variant, tenant: 200)
            action_specs = {"create": _action()}

        with pytest.raises(ImproperlyConfigured, match=r"\['tenant'\].*'variant'"):
            _ViewSet.as_view({"post": "create"})

    def test_a_finalizer_key_the_pool_still_lacks_is_refused_beside_it(self) -> None:
        class _ViewSet(ServiceViewSet):
            response_finalizer = staticmethod(lambda *, variant, tenant: None)
            action_specs = {"create": _action()}

        with pytest.raises(ImproperlyConfigured, match=r"\['tenant'\].*'variant'"):
            _ViewSet.as_view({"post": "create"})

    def test_a_refusal_offers_variant_where_a_discriminated_action_hands_it(self) -> None:
        # The ``keys`` arm the message reads: test_a_key_the_pool_still_lacks_is_refused_beside_it
        # holds the admitting half, and this that the message names it.
        class _ViewSet(ServiceViewSet):
            success_status = staticmethod(lambda *, tenant: 200)
            action_specs = {"create": _action()}

        with pytest.raises(ImproperlyConfigured, match="subset of .*'variant'"):
            _ViewSet.as_view({"post": "create"})

    def test_a_finalizer_s_refusal_offers_variant_too(self) -> None:
        class _ViewSet(ServiceViewSet):
            response_finalizer = staticmethod(lambda *, tenant: None)
            action_specs = {"create": _action()}

        with pytest.raises(ImproperlyConfigured, match="subset of .*'variant'"):
            _ViewSet.as_view({"post": "create"})

    def test_a_refusal_never_offers_variant_where_nothing_hands_it(self) -> None:
        # ``refuse_a_stray_variant`` has answered a callable declaring it, so the
        # conditional no longer decides what is refused here: only what the
        # message tells the author they may declare instead.
        class _ViewSet(ServiceViewSet):
            success_status = staticmethod(lambda *, tenant: 200)
            action_specs = {"create": _plain()}

        with pytest.raises(ImproperlyConfigured, match="subset of") as refused:
            _ViewSet.as_view({"post": "create"})
        assert "variant" not in str(refused.value)

    def test_a_finalizer_s_refusal_never_offers_variant_where_nothing_hands_it(self) -> None:
        class _ViewSet(ServiceViewSet):
            response_finalizer = staticmethod(lambda *, tenant: None)
            action_specs = {"create": _plain()}

        with pytest.raises(ImproperlyConfigured, match="subset of") as refused:
            _ViewSet.as_view({"post": "create"})
        assert "variant" not in str(refused.value)


ANSWERS = {
    "a status": ("success_status", _status),
    "a finalizer": ("response_finalizer", _finalizer),
    "a status with a default": ("success_status", _optional_status),
    "a finalizer with a default": ("response_finalizer", _optional_finalizer),
}


class TestVariantElsewhere:
    @pytest.mark.parametrize("case", ANSWERS)
    def test_on_a_standalone_view(self, case: str) -> None:
        seat, answer = ANSWERS[case]
        view = type("_View", (ServiceCreateView,), {"spec": _plain(), seat: staticmethod(answer)})
        with pytest.raises(ImproperlyConfigured, match=rf"`{seat}` declares `variant`"):
            view.as_view()

    @pytest.mark.parametrize("case", ANSWERS)
    def test_view_wide_through_a_plain_entry(self, case: str) -> None:
        seat, answer = ANSWERS[case]
        attrs = {
            "action_specs": {"create": _plain()},
            seat: staticmethod(answer),
        }
        view = type("_ViewSet", (ServiceViewSet,), attrs)
        with pytest.raises(ImproperlyConfigured, match=rf"`{seat}` declares `variant`"):
            view.as_view({"post": "create"})

    @pytest.mark.parametrize("case", ANSWERS)
    def test_a_view_wide_answer_is_refused_beside_a_discriminated_entry_too(
        self, case: str
    ) -> None:
        """The plain entry would be handed no ``variant``, whatever its neighbour is."""
        seat, answer = ANSWERS[case]
        attrs = {
            "action_specs": {"create": _action(), "destroy": _on_a_row()},
            seat: staticmethod(answer),
        }
        view = type("_ViewSet", (ServiceViewSet,), attrs)
        with pytest.raises(ImproperlyConfigured, match=rf"`{seat}` declares `variant`"):
            view.as_view({"post": "create"})

    @pytest.mark.parametrize("seat", ["success_status", "response_finalizer"])
    def test_a_per_action_hook_on_a_plain_entry(self, seat: str) -> None:
        def hook(self: Any, *, variant: str) -> Any: ...

        attrs = {"action_specs": {"create": _plain()}, f"get_create_{seat}": hook}
        view = type("_ViewSet", (ServiceViewSet,), attrs)
        with pytest.raises(ImproperlyConfigured, match=rf"`{seat}` declares `variant`"):
            view.as_view({"post": "create"})

    @pytest.mark.parametrize("seat", ["success_status", "response_finalizer"])
    def test_a_patch_hook_over_a_plain_update_entry(self, seat: str) -> None:
        def hook(self: Any, *, variant: str) -> Any: ...

        attrs = {"action_specs": {"update": _on_a_row()}, f"get_partial_update_{seat}": hook}
        view = type("_ViewSet", (ServiceViewSet,), attrs)
        with pytest.raises(ImproperlyConfigured, match=rf"`{seat}` declares `variant`"):
            view.as_view({"patch": "partial_update"})

    @pytest.mark.parametrize("seat", ["success_status", "response_finalizer"])
    def test_a_decorator_s_value_on_a_plain_spec(self, seat: str) -> None:
        def answer(*, variant: str) -> Any: ...

        with pytest.raises(ImproperlyConfigured, match=rf"`{seat}` declares `variant`"):

            @service_action(_plain(), methods=["post"], **{seat: answer})
            def run(self: Any, request: Any) -> None:
                """Stubbed."""

    @pytest.mark.parametrize("seat", ["success_status", "response_finalizer"])
    def test_a_hook_on_a_plain_decorated_action(self, seat: str) -> None:
        def hook(self: Any, *, variant: str) -> Any: ...

        @service_action(_plain(), methods=["post"])
        def run(self: Any, request: Any) -> None:
            """Stubbed."""

        view = type("_ViewSet", (ServiceViewSet,), {"run": run, f"get_run_{seat}": hook})
        with pytest.raises(ImproperlyConfigured, match=rf"`{seat}` declares `variant`"):
            view.as_view({"post": "run"})

    @pytest.mark.parametrize("case", ANSWERS)
    def test_a_view_wide_answer_naming_variant_is_refused_beside_a_plain_decorated_action(
        self, case: str
    ) -> None:
        seat, answer = ANSWERS[case]

        @service_action(_plain(), methods=["post"])
        def run(self: Any, request: Any) -> None:
            """Stubbed."""

        view = type("_ViewSet", (ServiceViewSet,), {"run": run, seat: staticmethod(answer)})
        with pytest.raises(ImproperlyConfigured, match=rf"`{seat}` declares `variant`"):
            view.as_view({"post": "run"})

    def test_a_plain_decorated_action_with_its_own_answers_never_reads_the_view_s(self) -> None:
        class _ViewSet(ServiceViewSet):
            success_status = staticmethod(_status)
            response_finalizer = staticmethod(_finalizer)
            action_specs = {}

            @service_action(_action(), methods=["post"])
            def chosen(self, request: Any) -> None:
                """Stubbed."""

            @service_action(
                _plain(),
                methods=["post"],
                success_status=201,
                response_finalizer=lambda *, response: None,
            )
            def plain(self, request: Any) -> None:
                """Stubbed."""

        assert _post(_ViewSet.as_view({"post": "plain"})).status_code == 201
        assert _post(_ViewSet.as_view({"post": "chosen"})).status_code == 202

    def test_a_plain_decorated_action_with_its_own_hooks_never_reads_the_view_s(self) -> None:
        class _ViewSet(ServiceViewSet):
            success_status = staticmethod(_status)
            response_finalizer = staticmethod(_finalizer)

            @service_action(_plain(), methods=["post"])
            def plain(self, request: Any) -> None:
                """Stubbed."""

            def get_plain_success_status(self) -> int:
                return 201

            def get_plain_response_finalizer(self) -> None: ...

        assert _post(_ViewSet.as_view({"post": "plain"})).status_code == 201

    def test_a_selector_action_answers_with_neither_so_is_not_asked(self) -> None:
        @selector_action(
            SelectorSpec(selector=lambda: [], kind=SelectorKind.LIST, permissions=_OPEN)
        )
        def read(self: Any, request: Any) -> None:
            """Stubbed."""

        attrs = {"read": read, "success_status": staticmethod(_status)}
        view = type("_ViewSet", (ServiceViewSet,), attrs)
        assert view.as_view({"get": "read"}) is not None

    def test_a_view_s_int_status_beside_a_plain_decorated_action_is_left_alone(self) -> None:
        class _ViewSet(ServiceViewSet):
            success_status = 202

            @service_action(_plain(), methods=["post"])
            def plain(self, request: Any) -> None:
                """Stubbed."""

        assert _post(_ViewSet.as_view({"post": "plain"})).status_code == 202

    def test_a_catch_all_named_variant_is_no_declaration(self) -> None:
        def answer(**variant: Any) -> int:
            return 200 if "variant" not in variant else 500

        view = type(
            "_View",
            (ServiceCreateView,),
            {"spec": _plain(), "success_status": staticmethod(answer)},
        ).as_view()
        assert _post(view, "/").status_code == 200

    def test_a_plain_call_hands_a_catch_all_no_variant(self) -> None:
        seen: dict[str, Any] = {}

        def answer(**kwargs: Any) -> int:
            seen.update(kwargs)
            return 200

        view = type(
            "_View",
            (ServiceCreateView,),
            {"spec": _plain(), "success_status": staticmethod(answer)},
        ).as_view()
        _post(view, "/")
        assert "variant" not in seen
