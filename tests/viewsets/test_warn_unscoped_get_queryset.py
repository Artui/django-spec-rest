from __future__ import annotations

import warnings
from typing import Any

import pytest
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import GenericViewSet

from django_spec_rest import (
    DiscriminatedAction,
    SelectorListMixin,
    SelectorViewSet,
    ServiceUpdateMixin,
    ServiceViewSet,
    selector_action,
    service_action,
)
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

_OPEN = (Unrestricted(),)
_BY_PK = Parameters.of(Parameter("pk", "integer", required=True))
_ID = r"django_spec_rest\.W001"

_LIST = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=lambda: Author.objects.none(),
    permissions=_OPEN,
)
_RETRIEVE = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
    reads=_BY_PK,
    permissions=_OPEN,
)
_TARGET = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
    reads=_BY_PK,
)


def _delete(*, instance: Author) -> None:
    instance.delete()


_DESTROY = ServiceSpec(service=_delete, permissions=_OPEN, instance_selector_spec=_TARGET)
_CREATE = ServiceSpec(service=lambda: None, permissions=_OPEN)


class _Scoped:
    """A project's mixin: its filter is what the move stops running."""

    def get_queryset(self) -> Any:
        return Author.objects.filter(name="mine")


def _reports(viewset: Any, actions: dict[str, str], **initkwargs: Any) -> list[str]:
    """Every report mounting ``viewset`` makes, as its text."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        viewset.as_view(actions, **initkwargs)
    return [str(w.message) for w in caught if "django_spec_rest.W001" in str(w.message)]


class TestAnOverrideBesideASpecIsReported:
    def test_beside_a_write_spec(self) -> None:
        class V(ServiceViewSet):
            action_specs = {"destroy": _DESTROY}

            def get_queryset(self) -> Any:
                return Author.objects.none()

        with pytest.warns(UserWarning, match=_ID):
            V.as_view({"delete": "destroy"})

    def test_beside_a_create_spec_which_is_a_write_too(self) -> None:
        class V(_Scoped, ServiceViewSet):
            action_specs = {"create": _CREATE}

        assert _reports(V, {"post": "create"})

    def test_beside_a_list_spec(self) -> None:
        class V(SelectorViewSet):
            action_specs = {"list": _LIST}

            def get_queryset(self) -> Any:
                return Author.objects.none()

        assert _reports(V, {"get": "list"})

    def test_beside_a_service_action(self) -> None:
        class V(_Scoped, ServiceViewSet):
            @service_action(_DESTROY, detail=True, methods=["post"])
            def archive(self, request: Any, pk: Any = None) -> None:
                """Stubbed: the decorator serves the spec."""

        assert _reports(V, {"post": "archive"})

    def test_beside_a_selector_action_of_the_list_kind(self) -> None:
        class V(_Scoped, ServiceViewSet):
            @selector_action(_LIST)
            def every(self, request: Any) -> None:
                """Stubbed: the decorator serves the spec."""

        assert _reports(V, {"get": "every"})

    def test_beside_specs_handed_to_as_view(self) -> None:
        class V(_Scoped, ServiceViewSet): ...

        assert _reports(V, {"get": "list"}, action_specs={"list": _LIST})

    def test_on_a_viewset_composed_of_a_mixin_alone(self) -> None:
        class V(_Scoped, ServiceUpdateMixin, GenericViewSet):
            action_specs = {"update": _DESTROY}

        assert _reports(V, {"put": "update"})

    def test_from_a_mixin_below_the_package_s_own_bases(self) -> None:
        """Python resolves ``get_queryset`` to the package's method, whose ``super()`` runs it."""

        class V(SelectorListMixin, _Scoped, GenericViewSet):
            action_specs = {"list": _LIST}

        assert _reports(V, {"get": "list"})

    def test_inherited_from_a_project_s_base(self) -> None:
        class Base(_Scoped, ServiceViewSet): ...

        class V(Base):
            action_specs = {"list": _LIST}

        assert _reports(V, {"get": "list"})

    def test_beside_a_retrieve_spec_alone(self) -> None:
        """A retrieve ignores ``get_queryset()`` as a write or a list does: a cross-tenant read."""

        class V(_Scoped, SelectorViewSet):
            action_specs = {"retrieve": _RETRIEVE}

        assert _reports(V, {"get": "retrieve"})

    def test_beside_a_selector_action_of_the_retrieve_kind(self) -> None:
        class V(_Scoped, ServiceViewSet):
            @selector_action(_RETRIEVE)
            def one(self, request: Any, pk: Any = None) -> None:
                """Stubbed: the decorator serves the spec."""

        assert _reports(V, {"get": "one"})

    def test_beside_a_retrieve_spec_handed_to_as_view(self) -> None:
        class V(_Scoped, ServiceViewSet): ...

        assert _reports(V, {"get": "retrieve"}, action_specs={"retrieve": _RETRIEVE})

    def test_and_a_retrieve_only_viewset_is_silenced_as_the_others_are(self) -> None:
        class V(_Scoped, SelectorViewSet):
            action_specs = {"retrieve": _RETRIEVE}
            spec_rows_scoped_by_selector = True

        assert _reports(V, {"get": "retrieve"}) == []


class TestADiscriminatedActionServesAWrite:
    """Neither lane that built these could see the other's type, so the pair is held here."""

    @pytest.mark.parametrize(
        ("action_name", "method", "variant"),
        [
            ("create", "post", _CREATE),
            ("update", "put", _DESTROY),
            ("partial_update", "patch", _DESTROY),
            ("destroy", "delete", _DESTROY),
        ],
    )
    def test_under_an_action_specs_entry(
        self, action_name: str, method: str, variant: ServiceSpec
    ) -> None:
        class V(_Scoped, ServiceViewSet):
            action_specs = {action_name: DiscriminatedAction(lambda: "only", {"only": variant})}

        assert _reports(V, {method: action_name})

    def test_under_a_service_action(self) -> None:
        class V(_Scoped, ServiceViewSet):
            @service_action(
                DiscriminatedAction(lambda: "only", {"only": _DESTROY}),
                detail=True,
                methods=["post"],
            )
            def archive(self, request: Any, pk: Any = None) -> None:
                """Stubbed: the decorator serves the spec."""

        assert _reports(V, {"post": "archive"})

    def test_it_is_asked_nothing_of_the_discriminator(self) -> None:
        def refuse_to_choose() -> str:
            raise AssertionError("as_view() has no request to choose a variant with")

        class V(_Scoped, ServiceViewSet):
            action_specs = {"create": DiscriminatedAction(refuse_to_choose, {"only": _CREATE})}

        assert _reports(V, {"post": "create"})

    def test_and_says_nothing_with_no_override(self) -> None:
        class V(ServiceViewSet):
            action_specs = {"create": DiscriminatedAction(lambda: "only", {"only": _CREATE})}

        assert not _reports(V, {"post": "create"})


class TestTheReportCarries:
    @pytest.fixture
    def report(self) -> str:
        class TenantViewSet(_Scoped, ServiceViewSet):
            action_specs = {"list": _LIST}

        reports = _reports(TenantViewSet, {"get": "list"})
        assert len(reports) == 1
        return reports[0]

    def test_the_id_first_so_a_filter_can_match_it(self, report: str) -> None:
        assert report.startswith("django_spec_rest.W001: ")

    def test_the_class(self, report: str) -> None:
        assert "TenantViewSet" in report

    def test_the_class_the_override_is_on(self, report: str) -> None:
        assert "_Scoped" in report

    def test_the_moving_page_s_section(self, report: str) -> None:
        assert "moving-from-drfs/#views-and-viewsets" in report

    def test_the_attribute_that_silences_it(self, report: str) -> None:
        assert "spec_rows_scoped_by_selector" in report


class TestSilent:
    def test_with_no_override_over_the_package_s_own_get_queryset(self) -> None:
        """``SelectorListMixin`` and DRF both define it, and neither is the project's."""

        class V(ServiceViewSet):
            action_specs = {"list": _LIST, "destroy": _DESTROY}

        assert _reports(V, {"get": "list", "delete": "destroy"}) == []

    def test_for_a_spec_less_action(self) -> None:
        class V(_Scoped, ServiceViewSet):
            @action(detail=False)
            def ping(self, request: Any) -> Response:
                return Response({})

        assert _reports(V, {"get": "ping"}) == []


class TestSilencingPerClass:
    def test_the_class_declaring_it_is_silent(self) -> None:
        class V(_Scoped, ServiceViewSet):
            action_specs = {"list": _LIST}
            spec_rows_scoped_by_selector = True

        assert _reports(V, {"get": "list"}) == []

    def test_only_that_class(self) -> None:
        class Silenced(_Scoped, ServiceViewSet):
            action_specs = {"list": _LIST}
            spec_rows_scoped_by_selector = True

        class Other(_Scoped, ServiceViewSet):
            action_specs = {"list": _LIST}

        assert _reports(Silenced, {"get": "list"}) == []
        assert _reports(Other, {"get": "list"})

    def test_a_base_vouching_for_its_own_override_covers_its_subclasses(self) -> None:
        class Base(_Scoped, ServiceViewSet):
            spec_rows_scoped_by_selector = True

        class V(Base):
            action_specs = {"list": _LIST}

        assert _reports(V, {"get": "list"}) == []

    def test_a_base_never_vouches_for_an_override_added_beneath_it(self) -> None:
        """The failure is silent, so a base's word covers only what it could have read."""

        class Base(ServiceViewSet):
            spec_rows_scoped_by_selector = True

        class V(_Scoped, Base):
            action_specs = {"list": _LIST}

        assert _reports(V, {"get": "list"})

    def test_a_base_never_vouches_for_a_subclass_s_own_override(self) -> None:
        class Base(_Scoped, ServiceViewSet):
            spec_rows_scoped_by_selector = True

        class V(Base):
            action_specs = {"list": _LIST}

            def get_queryset(self) -> Any:
                return Author.objects.none()

        assert _reports(V, {"get": "list"})

    def test_a_subclass_may_take_the_word_back(self) -> None:
        class Base(_Scoped, ServiceViewSet):
            spec_rows_scoped_by_selector = True

        class V(Base):
            action_specs = {"list": _LIST}
            spec_rows_scoped_by_selector = False

        assert _reports(V, {"get": "list"})


class TestWhenItIsMade:
    def test_a_router_mounting_a_viewset_twice_shows_it_once(self) -> None:
        """A router calls ``as_view()`` per route, each from one line, and the text is the same."""

        class V(_Scoped, ServiceViewSet):
            action_specs = {"list": _LIST, "destroy": _DESTROY}

        router = SimpleRouter()
        router.register("v", V, basename="v")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("default")
            _ = router.urls
        assert len([w for w in caught if "django_spec_rest.W001" in str(w.message)]) == 1

    def test_a_request_makes_no_report(self) -> None:
        class V(_Scoped, ServiceViewSet):
            action_specs = {"list": _LIST}
            serializer_class = AuthorSerializer

        with pytest.warns(UserWarning, match=_ID):
            view = V.as_view({"get": "list"})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            response = view(APIRequestFactory().get("/"))
        assert response.status_code == 200
        assert [w for w in caught if "django_spec_rest.W001" in str(w.message)] == []

    def test_a_project_may_make_it_an_error_by_its_id(self) -> None:
        class V(_Scoped, ServiceViewSet):
            action_specs = {"list": _LIST}

        with warnings.catch_warnings(), pytest.raises(UserWarning, match=_ID):
            warnings.filterwarnings("error", message=_ID)
            V.as_view({"get": "list"})

    def test_it_names_the_line_mounting_the_viewset(self) -> None:
        class V(_Scoped, ServiceViewSet):
            action_specs = {"list": _LIST}

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            V.as_view({"get": "list"})
        report = next(w for w in caught if "django_spec_rest.W001" in str(w.message))
        assert report.filename == __file__

    def test_a_router_mounted_viewset_reports_from_the_routers_module(self) -> None:
        # The router calls ``as_view()``, so the report's location is DRF's, as
        # the reference page says; the text still names the class.
        class V(_Scoped, ServiceViewSet):
            action_specs = {"list": _LIST}

        router = SimpleRouter()
        router.register("v", V, basename="v")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _ = router.urls
        report = next(w for w in caught if "django_spec_rest.W001" in str(w.message))
        assert report.filename.replace("\\", "/").endswith("rest_framework/routers.py")
        assert "V" in str(report.message)
