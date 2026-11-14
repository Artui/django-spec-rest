from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.http import FileResponse, HttpResponseBase, StreamingHttpResponse
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
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from django_spec_rest import (
    DiscriminatedAction,
    SelectorListView,
    SelectorRetrieveView,
    SelectorViewSet,
    ServiceCreateView,
    ServiceViewSet,
    selector_action,
    service_action,
)
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()
_OPEN = (Unrestricted(),)
_PK = Parameters.of(Parameter("pk", "integer", required=True))
_CSV = b"name\nAda\n"


def _report(**_: Any) -> FileResult:
    return FileResult(_CSV, filename="report.csv")


def _export(**fields: Any) -> ServiceSpec:
    fields.setdefault("service", _report)
    fields.setdefault("presenter", FilePresenter("text/csv"))
    return ServiceSpec(permissions=_OPEN, atomic=False, **fields)


def _author(*, pk: int) -> Author | None:
    return Author.objects.filter(pk=pk).first()


def _pdf_of(author: Author) -> bytes:
    return f"%PDF {author.name}".encode()


def _invoice(**fields: Any) -> SelectorSpec:
    fields.setdefault("kind", SelectorKind.RETRIEVE)
    if fields["kind"] is SelectorKind.RETRIEVE:
        fields.update(reads=_PK, selector=_author)
    else:
        fields["selector"] = Author.objects.all
    return SelectorSpec(
        permissions=_OPEN,
        presenter=FilePresenter(
            "application/pdf", filename=lambda author: f"author-{author.pk}.pdf", render=_pdf_of
        ),
        **fields,
    )


def _body(response: HttpResponseBase) -> bytes:
    assert isinstance(response, StreamingHttpResponse)
    return b"".join(response.streaming_content)  # ty: ignore[invalid-argument-type]


def _post(view: Any, accept: str = "*/*") -> HttpResponseBase:
    return view(factory.post("/", {}, format="json", HTTP_ACCEPT=accept))


def _get(view: Any, pk: int, accept: str = "*/*") -> HttpResponseBase:
    return view(factory.get("/", HTTP_ACCEPT=accept), pk=str(pk))


@pytest.fixture
def ada() -> Author:
    return Author.objects.create(name="Ada")


class Exports(ServiceViewSet):
    queryset = Author.objects.all()
    action_specs = {"create": _export()}

    @service_action(_export(), detail=False, methods=["post"])
    def export(self, request: Any) -> Any: ...


class Invoices(SelectorViewSet):
    queryset = Author.objects.all()
    action_specs = {"retrieve": _invoice()}

    @selector_action(_invoice(), url_path="pdf")
    def pdf(self, request: Any, pk: Any = None) -> Any: ...


class TestAServiceSpecPresentingAFile:
    @pytest.mark.parametrize(
        ("view", "status"),
        [
            (type("_Export", (ServiceCreateView,), {"spec": _export()}).as_view(), 201),
            (Exports.as_view({"post": "create"}), 201),
            (Exports.as_view({"post": "export"}), 200),
        ],
        ids=["view", "viewset", "service-action"],
    )
    def test_it_answers_the_bytes_as_an_attachment(self, view: Any, status: int) -> None:
        response = _post(view)
        assert isinstance(response, FileResponse)
        assert response.status_code == status
        assert _body(response) == _CSV
        assert response["Content-Type"] == "text/csv"
        assert response["Content-Disposition"] == 'attachment; filename="report.csv"'
        assert response["Content-Length"] == str(len(_CSV))

    def test_a_file_object_is_streamed_from_the_file(self) -> None:
        handle = io.BytesIO(_CSV)
        spec = _export(service=lambda: FileResult(handle, filename="report.csv"))
        response = _post(type("_V", (ServiceCreateView,), {"spec": spec}).as_view())
        assert isinstance(response, FileResponse)
        assert _body(response) == _CSV
        response.close()
        assert handle.closed

    def test_an_iterable_of_bytes_is_streamed_under_the_same_headers(self) -> None:
        def chunks() -> Iterator[bytes]:
            yield b"name\n"
            yield b"Ada\n"

        spec = _export(service=lambda: FileResult(chunks(), filename="report.csv"))
        response = _post(type("_V", (ServiceCreateView,), {"spec": spec}).as_view())
        assert type(response) is StreamingHttpResponse
        assert response.status_code == 201
        assert _body(response) == _CSV
        assert response["Content-Type"] == "text/csv"
        assert response["Content-Disposition"] == 'attachment; filename="report.csv"'
        # No size is known without reading the whole stream.
        assert not response.has_header("Content-Length")

    def test_a_declared_size_is_the_content_length_of_a_stream(self) -> None:
        spec = _export(service=lambda: FileResult(iter([_CSV]), filename="r.csv", size=10))
        response = _post(type("_V", (ServiceCreateView,), {"spec": spec}).as_view())
        assert response["Content-Length"] == "10"

    def test_a_name_outside_ascii_is_quoted_as_rfc_5987(self) -> None:
        spec = _export(service=lambda: FileResult(iter([_CSV]), filename="résumé.csv"))
        response = _post(type("_V", (ServiceCreateView,), {"spec": spec}).as_view())
        assert (
            response["Content-Disposition"] == "attachment; filename*=utf-8''r%C3%A9sum%C3%A9.csv"
        )

    def test_nothing_under_allow_none_is_a_204(self) -> None:
        spec = _export(service=lambda: None, allow_none=True)
        response = _post(type("_V", (ServiceCreateView,), {"spec": spec}).as_view())
        assert response.status_code == 204

    def test_the_response_finalizer_receives_the_file_response(self) -> None:
        received: list[HttpResponseBase] = []

        def inline(response: HttpResponseBase) -> HttpResponseBase:
            received.append(response)
            response["Content-Disposition"] = 'inline; filename="report.csv"'
            return response

        view = type(
            "_V", (ServiceCreateView,), {"spec": _export(), "response_finalizer": inline}
        ).as_view()
        response = _post(view)
        assert received == [response]
        assert isinstance(response, FileResponse)
        assert response["Content-Disposition"] == 'inline; filename="report.csv"'


class TestARetrieveSelectorSpecPresentingAFile:
    @pytest.mark.parametrize(
        "view",
        [
            type("_Invoice", (SelectorRetrieveView,), {"spec": _invoice()}).as_view(),
            Invoices.as_view({"get": "retrieve"}),
            Invoices.as_view({"get": "pdf"}),
        ],
        ids=["view", "mixin", "selector-action"],
    )
    def test_it_answers_the_rendered_row_as_an_attachment(self, view: Any, ada: Author) -> None:
        response = _get(view, ada.pk)
        assert isinstance(response, FileResponse)
        assert response.status_code == 200
        assert _body(response) == b"%PDF Ada"
        assert response["Content-Type"] == "application/pdf"
        assert response["Content-Disposition"] == f'attachment; filename="author-{ada.pk}.pdf"'

    def test_a_miss_is_still_a_404(self) -> None:
        view = type("_Invoice", (SelectorRetrieveView,), {"spec": _invoice()}).as_view()
        assert _get(view, 999).status_code == 404


class TestAFileOfManyIsRefusedAtAsView:
    def test_a_list_selector_view(self) -> None:
        view = type("Listing", (SelectorListView,), {"spec": _invoice(kind=SelectorKind.LIST)})
        with pytest.raises(ImproperlyConfigured, match=r"^Listing: SelectorSpec presents a file"):
            view.as_view()

    def test_a_viewset_s_list_entry(self) -> None:
        viewset = type(
            "Listing",
            (SelectorViewSet,),
            {
                "queryset": Author.objects.all(),
                "action_specs": {"list": _invoice(kind=SelectorKind.LIST)},
            },
        )
        with pytest.raises(ImproperlyConfigured, match="presents a list of rows"):
            viewset.as_view({"get": "list"})

    def test_a_list_selector_action_where_it_is_decorated(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"^@selector_action .* list of rows"):

            @selector_action(_invoice(kind=SelectorKind.LIST))
            def every(self: Any, request: Any) -> None: ...

    def test_a_returns_many_service_view(self) -> None:
        view = type("Bulk", (ServiceCreateView,), {"spec": _export(returns_many=True)})
        with pytest.raises(ImproperlyConfigured, match=r"^Bulk: .* is declared returns_many"):
            view.as_view()

    def test_presented_affordances(self) -> None:
        opened = ServiceSpec(service=lambda: None, permissions=_OPEN)
        spec = _invoice(affordances={"open": opened})
        view = type("Invoice", (SelectorRetrieveView,), {"spec": spec})
        with pytest.raises(ImproperlyConfigured, match="presents affordances"):
            view.as_view()

    def test_a_service_action_is_refused_where_it_is_decorated(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"^@service_action .* returns_many"):

            @service_action(_export(returns_many=True), detail=False, methods=["post"])
            def bulk(self: Any, request: Any) -> None: ...


def _created(**_: Any) -> Author:
    return Author.objects.create(name="Ada")


class TestAFileThroughTheOutputSelector:
    def test_a_retrieve_output_selector_answers_its_file(self) -> None:
        spec = ServiceSpec(
            service=_created,
            permissions=_OPEN,
            atomic=False,
            output_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, result: result,
                presenter=FilePresenter("application/pdf", filename="a.pdf", render=_pdf_of),
            ),
        )
        response = _post(type("_V", (ServiceCreateView,), {"spec": spec}).as_view())
        assert isinstance(response, FileResponse)
        assert response.status_code == 201
        assert _body(response) == b"%PDF Ada"

    def test_a_list_output_selector_is_refused_naming_the_view(self) -> None:
        listing = _invoice(kind=SelectorKind.LIST).derive(permissions=None)
        spec = ServiceSpec(
            service=_created, permissions=_OPEN, atomic=False, output_selector_spec=listing
        )
        view = type("Rows", (ServiceCreateView,), {"spec": spec})
        with pytest.raises(ImproperlyConfigured, match=r"^Rows: .* list of rows"):
            view.as_view()


class TestAFileIsTheSpecsNotTheValues:
    def test_a_file_result_from_another_presenter_is_not_a_download(self) -> None:
        class Passes(Presenter):
            def output(self) -> Output | None:
                return None

            def present(self, value: Any) -> Any:
                return value

        spec = ServiceSpec(service=_report, permissions=_OPEN, atomic=False, presenter=Passes())
        response = _post(type("_V", (ServiceCreateView,), {"spec": spec}).as_view())
        assert isinstance(response, Response)
        assert isinstance(response.data, FileResult)

    def test_the_presenter_s_type_is_the_file_s_whatever_its_name(self) -> None:
        spec = _export(presenter=FilePresenter("application/octet-stream"))
        response = _post(type("_V", (ServiceCreateView,), {"spec": spec}).as_view())
        assert response["Content-Type"] == "application/octet-stream"


class TestAsAttachmentFalseAnswersInline:
    def test_a_retrieve_view(self, ada: Author) -> None:
        attrs = {"spec": _invoice(), "as_attachment": False}
        response = _get(type("_V", (SelectorRetrieveView,), attrs).as_view(), ada.pk)
        assert isinstance(response, FileResponse)
        assert response["Content-Disposition"] == f'inline; filename="author-{ada.pk}.pdf"'

    def test_a_streamed_file(self) -> None:
        spec = _export(service=lambda: FileResult(iter([_CSV]), filename="report.csv"))
        attrs = {"spec": spec, "as_attachment": False}
        response = _post(type("_V", (ServiceCreateView,), attrs).as_view())
        assert response["Content-Disposition"] == 'inline; filename="report.csv"'

    def test_a_viewset_s_action(self, ada: Author) -> None:
        viewset = type("_Inline", (Invoices,), {"as_attachment": False})
        response = _get(viewset.as_view({"get": "pdf"}), ada.pk)
        assert response["Content-Disposition"].startswith("inline; ")


def _variants(**specs: Any) -> DiscriminatedAction:
    return DiscriminatedAction(lambda: "csv", specs)


class TestAnAcceptNamingTheFileIsServed:
    @pytest.mark.parametrize(
        ("view", "status"),
        [
            (type("_Export", (ServiceCreateView,), {"spec": _export()}).as_view(), 201),
            (Exports.as_view({"post": "create"}), 201),
            (Exports.as_view({"post": "export"}), 200),
            (
                type(
                    "_Either",
                    (ServiceViewSet,),
                    {
                        "action_specs": {
                            "create": _variants(
                                csv=_export(),
                                json=ServiceSpec(
                                    service=lambda: {}, permissions=_OPEN, atomic=False
                                ),
                            )
                        }
                    },
                ).as_view({"post": "create"}),
                201,
            ),
        ],
        ids=["view", "viewset", "service-action", "a-variant"],
    )
    def test_a_service_spec(self, view: Any, status: int) -> None:
        response = _post(view, accept="text/csv")
        assert isinstance(response, FileResponse)
        assert response.status_code == status

    @pytest.mark.parametrize(
        "view",
        [
            type("_Invoice", (SelectorRetrieveView,), {"spec": _invoice()}).as_view(),
            Invoices.as_view({"get": "retrieve"}),
            Invoices.as_view({"get": "pdf"}),
        ],
        ids=["view", "mixin", "selector-action"],
    )
    def test_a_retrieve_selector_spec(self, view: Any, ada: Author) -> None:
        response = _get(view, ada.pk, accept="application/pdf")
        assert isinstance(response, FileResponse)
        assert response.status_code == 200

    def test_a_refusal_under_it_is_json(self) -> None:
        view = type("_Invoice", (SelectorRetrieveView,), {"spec": _invoice()}).as_view()
        response = _get(view, 999, accept="application/pdf")
        assert response.status_code == 404
        assert isinstance(response.accepted_renderer, JSONRenderer)  # ty: ignore[unresolved-attribute]

    def test_a_type_the_file_is_not_is_still_a_406(self) -> None:
        view = type("_Export", (ServiceCreateView,), {"spec": _export()}).as_view()
        assert _post(view, accept="application/pdf").status_code == 406

    def test_a_spec_presenting_no_file_is_still_a_406(self) -> None:
        spec = ServiceSpec(service=lambda: {}, permissions=_OPEN, atomic=False)
        view = type("_V", (ServiceCreateView,), {"spec": spec}).as_view()
        assert _post(view, accept="text/csv").status_code == 406

    def test_a_request_serving_no_spec_is_still_a_406(self) -> None:
        response = Exports.as_view({"post": "create"})(factory.options("/", HTTP_ACCEPT="text/csv"))
        assert response.status_code == 406
