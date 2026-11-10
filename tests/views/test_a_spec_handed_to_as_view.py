from __future__ import annotations

from typing import Any

import django_filters
import pytest
from django.core.exceptions import ImproperlyConfigured
from django_filters.rest_framework import DjangoFilterBackend
from django_service_specs import (
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from django_spec_rest import (
    SelectorListView,
    SelectorRetrieveView,
    ServiceCreateView,
    ServiceDeleteView,
    ServiceUpdateView,
)
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)

_AUTHORS = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=lambda: Author.objects.order_by("pk"),
    permissions=_OPEN,
    presenter=SerializerPresenter(AuthorSerializer),
)
_ONE = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
    permissions=_OPEN,
    presenter=SerializerPresenter(AuthorSerializer),
)
_CREATE = ServiceSpec(service=lambda: Author.objects.create(name="Ada"), permissions=_OPEN)


class _Deny(PermissionCheck):
    def has_permission(self, *args: Any, **kwargs: Any) -> bool:
        return False


def _mount(base: type, how: str, **attrs: Any) -> Any:
    """``base`` built by ``as_view()`` with ``attrs`` as class attributes or as its keywords."""
    if how == "class attribute":
        return type("_View", (base,), attrs).as_view()
    return type("_View", (base,), {}).as_view(**attrs)


_HOW = pytest.mark.parametrize("how", ["class attribute", "as_view keyword"])


class TestARefusalAtMount:
    @_HOW
    @pytest.mark.parametrize("base", [ServiceUpdateView, ServiceDeleteView])
    def test_a_detail_spec_with_no_target_selector_is_refused(self, base: type, how: str) -> None:
        spec = ServiceSpec(service=lambda: None, permissions=_OPEN)
        with pytest.raises(ImproperlyConfigured, match="declares no target selector"):
            _mount(base, how, spec=spec)

    @_HOW
    def test_a_selector_spec_on_a_create_view_is_refused(self, how: str) -> None:
        with pytest.raises(ImproperlyConfigured, match="is a SelectorSpec"):
            _mount(ServiceCreateView, how, spec=_AUTHORS)

    @_HOW
    def test_a_keyword_nothing_fills_is_refused(self, how: str) -> None:
        spec = ServiceSpec(service=lambda *, nonsense: None, permissions=_OPEN)
        with pytest.raises(ImproperlyConfigured, match="nonsense"):
            _mount(ServiceCreateView, how, spec=spec)

    @_HOW
    @pytest.mark.parametrize(
        ("base", "spec"), [(SelectorListView, _ONE), (SelectorRetrieveView, _AUTHORS)]
    )
    def test_a_spec_of_the_other_kind_is_refused(
        self, base: type, spec: SelectorSpec, how: str
    ) -> None:
        with pytest.raises(ImproperlyConfigured, match="spec.kind is"):
            _mount(base, how, spec=spec)

    @_HOW
    def test_a_service_spec_on_a_selector_view_is_refused(self, how: str) -> None:
        with pytest.raises(ImproperlyConfigured, match="is a ServiceSpec"):
            _mount(SelectorListView, how, spec=_CREATE)

    @_HOW
    def test_a_success_status_the_view_cannot_resolve_is_refused(self, how: str) -> None:
        with pytest.raises(ImproperlyConfigured, match="success_status"):
            _mount(ServiceCreateView, how, spec=_CREATE, success_status=lambda *, nonsense: 201)

    @_HOW
    def test_a_finalizer_the_view_cannot_call_is_refused(self, how: str) -> None:
        with pytest.raises(ImproperlyConfigured, match="response_finalizer"):
            _mount(
                ServiceCreateView,
                how,
                spec=_CREATE,
                response_finalizer=lambda *, nonsense: None,
            )

    def test_a_filter_set_beside_a_keyword_s_django_filter_backend_is_refused(self) -> None:
        """The backend the keyword sets is the one DRF's ``filter_queryset`` reads."""

        class _ByName(django_filters.FilterSet):
            class Meta:
                model = Author
                fields = ["name"]

        spec = SelectorSpec(
            kind=SelectorKind.LIST,
            selector=Author.objects.all,
            permissions=_OPEN,
            filter_set=_ByName,
        )
        with pytest.raises(ImproperlyConfigured, match="DjangoFilterBackend"):
            SelectorListView.as_view(spec=spec, filter_backends=[DjangoFilterBackend])

    def test_the_refusal_names_the_view_s_own_class(self) -> None:
        class _Rename(ServiceUpdateView): ...

        spec = ServiceSpec(service=lambda: None, permissions=_OPEN)
        with pytest.raises(ImproperlyConfigured, match=r"^_Rename\.spec declares"):
            _Rename.as_view(spec=spec)


class TestAKeywordSpecServed:
    def test_a_list_view_serves_its_rows(self) -> None:
        ada = Author.objects.create(name="Ada")
        response: Response = SelectorListView.as_view(spec=_AUTHORS)(factory.get("/"))
        assert response.status_code == 200
        assert response.data == [{"id": ada.pk, "name": "Ada"}]

    def test_a_retrieve_view_serves_its_row(self) -> None:
        ada = Author.objects.create(name="Ada")
        response: Response = SelectorRetrieveView.as_view(spec=_ONE)(factory.get("/"), pk=ada.pk)
        assert response.status_code == 200
        assert response.data == {"id": ada.pk, "name": "Ada"}

    def test_a_keyword_outranks_the_class_s_spec(self) -> None:
        ada = Author.objects.create(name="Ada")

        class _Nobody(SelectorListView):
            spec = SelectorSpec(
                kind=SelectorKind.LIST,
                selector=Author.objects.none,
                permissions=_OPEN,
                presenter=SerializerPresenter(AuthorSerializer),
            )

        response: Response = _Nobody.as_view(spec=_AUTHORS)(factory.get("/"))
        assert response.data == [{"id": ada.pk, "name": "Ada"}]

    def test_a_create_view_answers_with_the_keyword_s_success_status(self) -> None:
        view = ServiceCreateView.as_view(spec=_CREATE, success_status=202)
        assert view(factory.post("/", {}, format="json")).status_code == 202

    def test_a_create_view_runs_the_keyword_s_finalizer(self) -> None:
        def finalize(*, response: Response) -> Response:
            response["X-Finalized"] = "yes"
            return response

        view = ServiceCreateView.as_view(spec=_CREATE, response_finalizer=finalize)
        assert view(factory.post("/", {}, format="json"))["X-Finalized"] == "yes"

    @pytest.mark.parametrize("base", [SelectorListView, SelectorRetrieveView])
    def test_a_keyword_spec_s_permissions_are_asked_over_the_class_s_queryset(
        self, base: type
    ) -> None:
        """A view also declaring DRF's ``queryset`` is served by the keyword's spec."""
        ada = Author.objects.create(name="Ada")
        kind = SelectorKind.LIST if base is SelectorListView else SelectorKind.RETRIEVE
        spec = SelectorSpec(
            kind=kind,
            selector=Author.objects.all if kind is SelectorKind.LIST else Author.objects.first,
            permissions=(_Deny(),),
            presenter=SerializerPresenter(AuthorSerializer),
        )
        attrs = {"queryset": Author.objects.all(), "serializer_class": AuthorSerializer}
        view = type("_View", (base,), attrs).as_view(spec=spec)
        response: Response = view(factory.get("/"), pk=ada.pk)
        assert response.status_code == 403
        assert "Ada" not in str(response.data)
