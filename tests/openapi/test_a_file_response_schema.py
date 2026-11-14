from __future__ import annotations

from typing import Any

import pytest
from django.urls import path
from django_service_specs import (
    FilePresenter,
    FileResult,
    Output,
    Parameter,
    Parameters,
    Presenter,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from drf_spectacular.generators import SchemaGenerator
from rest_framework.routers import DefaultRouter

from django_spec_rest import (
    SelectorRetrieveView,
    SelectorViewSet,
    ServiceCreateView,
    ServiceViewSet,
    selector_action,
    service_action,
)
from django_spec_rest.openapi import enable_openapi
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db

_OPEN = (Unrestricted(),)
_PK = Parameters.of(Parameter("pk", "integer", required=True))
_BINARY = {"type": "string", "format": "binary"}


def _report(**_: Any) -> FileResult:
    return FileResult(b"a,b\n", filename="report.csv")


def _nothing(**_: Any) -> None: ...


def _service(**fields: Any) -> ServiceSpec:
    fields.setdefault("service", _report)
    return ServiceSpec(
        permissions=_OPEN, atomic=False, presenter=FilePresenter("text/csv"), **fields
    )


def _invoice(*, pk: int) -> Author | None:
    return Author.objects.filter(pk=pk).first()


def _selector() -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=_invoice,
        reads=_PK,
        permissions=_OPEN,
        presenter=FilePresenter("application/pdf", filename="invoice.pdf", render=lambda _: b""),
    )


class _Shapeless(Presenter):
    """A presenter of no declared JSON shape, as the kernel lets ``output()`` answer."""

    def output(self) -> Output | None:
        return None

    def present(self, value: Any) -> Any:
        return value


class Export(ServiceCreateView):
    spec = _service()


class ExportOrNothing(ServiceCreateView):
    spec = _service(service=_nothing, allow_none=True)


class Shapeless(ServiceCreateView):
    spec = ServiceSpec(service=_report, permissions=_OPEN, atomic=False, presenter=_Shapeless())


class Invoice(SelectorRetrieveView):
    spec = _selector()


class Exports(ServiceViewSet):
    queryset = Author.objects.all()
    action_specs = {"create": _service()}

    @service_action(_service(), detail=False, methods=["post"])
    def export(self, request: Any) -> Any: ...


class Invoices(SelectorViewSet):
    queryset = Author.objects.all()
    action_specs = {"retrieve": _selector()}

    @selector_action(_selector(), url_path="pdf")
    def pdf(self, request: Any, pk: Any = None) -> Any: ...


_router = DefaultRouter()
_router.register("exports", Exports, basename="exports")
_router.register("invoices", Invoices, basename="invoices")

urlpatterns = [
    path("export/", Export.as_view()),
    path("export-or-nothing/", ExportOrNothing.as_view()),
    path("shapeless/", Shapeless.as_view()),
    path("invoice/<int:pk>/", Invoice.as_view()),
    *_router.urls,
]


@pytest.fixture(scope="module", autouse=True)
def _enable_openapi() -> None:
    enable_openapi()


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)


def _success(schema: dict[str, Any], route: str, method: str, status: str) -> dict[str, Any]:
    return schema["paths"][route][method]["responses"][status]


class TestAFileSpecIsDocumentedAsBinary:
    @pytest.mark.parametrize(
        ("route", "method", "status", "content_type"),
        [
            ("/export/", "post", "201", "text/csv"),
            ("/exports/", "post", "201", "text/csv"),
            ("/exports/export/", "post", "200", "text/csv"),
            ("/invoice/{id}/", "get", "200", "application/pdf"),
            ("/invoices/{id}/", "get", "200", "application/pdf"),
            ("/invoices/{id}/pdf/", "get", "200", "application/pdf"),
        ],
        ids=["service-view", "viewset", "service-action", "retrieve-view", "mixin", "action"],
    )
    def test_the_success_is_the_presenter_s_content_type_carrying_binary(
        self, schema: dict[str, Any], route: str, method: str, status: str, content_type: str
    ) -> None:
        assert _success(schema, route, method, status)["content"] == {
            content_type: {"schema": _BINARY}
        }

    def test_a_file_spec_that_may_present_nothing_documents_the_204_beside_it(
        self, schema: dict[str, Any]
    ) -> None:
        responses = schema["paths"]["/export-or-nothing/"]["post"]["responses"]
        assert responses["201"]["content"] == {"text/csv": {"schema": _BINARY}}
        assert "content" not in responses["204"]


def test_a_presenter_of_no_json_shape_documents_any_value(schema: dict[str, Any]) -> None:
    content = _success(schema, "/shapeless/", "post", "201")["content"]
    assert content == {"application/json": {"schema": {}}}
