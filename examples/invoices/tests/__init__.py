"""End-to-end tests of the example: one class per behaviour the README lists."""

from __future__ import annotations

from django.contrib.auth.models import AnonymousUser, User
from django_service_specs import NotPermitted, dispatch
from rest_framework import status
from rest_framework.test import APITestCase

from invoices.models import Invoice
from invoices.views import SEND_SPEC, UPDATE_SPEC


def _invoice(**fields: object) -> Invoice:
    return Invoice.objects.create(**{"customer": "Acme", "amount_cents": 4200, **fields})


class SpecOnAViewSetTests(APITestCase):
    """The viewset's ``action_specs`` serve list, retrieve, create and update."""

    def test_create_validates_with_the_serializer_and_presents_the_row(self) -> None:
        response = self.client.post("/invoices/", {"customer": "Acme", "amount_cents": 4200})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["customer"], "Acme")
        self.assertEqual(response.data["status"], Invoice.STATUS_DRAFT)
        self.assertTrue(Invoice.objects.filter(pk=response.data["id"]).exists())

    def test_retrieve_reads_the_pk_from_the_route(self) -> None:
        invoice = _invoice()

        response = self.client.get(f"/invoices/{invoice.pk}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], invoice.pk)

    def test_a_patch_validates_only_what_it_sends(self) -> None:
        invoice = _invoice()

        response = self.client.patch(f"/invoices/{invoice.pk}/", {"notes": "Net 30"})

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        invoice.refresh_from_db()
        self.assertEqual(invoice.notes, "Net 30")

    def test_a_put_validates_every_required_field(self) -> None:
        invoice = _invoice()

        response = self.client.put(f"/invoices/{invoice.pk}/", {"notes": "Net 30"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(set(response.data), {"customer", "amount_cents"})


class OffHttpTests(APITestCase):
    """The update spec the viewset serves runs through the kernel's ``dispatch``."""

    def test_the_kernel_s_dispatch_runs_the_route_s_spec(self) -> None:
        invoice = _invoice()
        user = User.objects.create_user("clerk")

        result = dispatch(
            UPDATE_SPEC,
            principal=user,
            arguments={"pk": invoice.pk, "customer": "Acme Ltd", "amount_cents": 4200},
        )

        self.assertEqual(result.value.customer, "Acme Ltd")
        invoice.refresh_from_db()
        self.assertEqual(invoice.customer, "Acme Ltd")


class SpecOnAViewTests(APITestCase):
    """``SentInvoiceListView`` serves one selector spec on its own route."""

    def test_the_view_answers_its_selector_s_rows(self) -> None:
        _invoice(customer="Draft Co")
        sent = _invoice(customer="Sent Co", status=Invoice.STATUS_SENT)

        response = self.client.get("/sent-invoices/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["id"] for row in response.data], [sent.pk])


class FilterOffTheQueryStringTests(APITestCase):
    """The list spec's ``filter_set`` is fed from the query string."""

    def setUp(self) -> None:
        self.draft = _invoice(customer="Acme")
        self.sent = _invoice(customer="Globex", status=Invoice.STATUS_SENT)

    def test_a_filter_narrows_the_rows(self) -> None:
        response = self.client.get("/invoices/?status=sent")

        self.assertEqual([row["id"] for row in response.data], [self.sent.pk])

    def test_a_lookup_expression_applies(self) -> None:
        response = self.client.get("/invoices/?customer=acm")

        self.assertEqual([row["id"] for row in response.data], [self.draft.pk])

    def test_a_blank_filter_is_absent(self) -> None:
        response = self.client.get("/invoices/?status=")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_a_value_the_filter_refuses_is_a_400(self) -> None:
        response = self.client.get("/invoices/?status=lost")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status", response.data)


class OptionsOnADetailRouteTests(APITestCase):
    """OPTIONS describes the route from its specs and runs none of them."""

    def test_allow_names_only_the_methods_a_spec_serves(self) -> None:
        invoice = _invoice()

        response = self.client.options(f"/invoices/{invoice.pk}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        allowed = set(response["Allow"].split(", "))
        # DRF serves HEAD wherever it serves GET; no spec serves DELETE.
        self.assertEqual(allowed, {"GET", "HEAD", "PUT", "PATCH", "OPTIONS"})
        self.assertEqual(
            self.client.delete(f"/invoices/{invoice.pk}/").status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def test_put_is_described_as_a_json_schema_less_the_route_s_capture(self) -> None:
        invoice = _invoice()

        schema = self.client.options(f"/invoices/{invoice.pk}/").data["actions"]["PUT"]

        self.assertEqual(schema["type"], "object")
        self.assertEqual(set(schema["properties"]), {"customer", "amount_cents", "notes"})
        self.assertNotIn("pk", schema["properties"])

    def test_no_stage_of_the_spec_runs(self) -> None:
        # The target lookup would query for the row; OPTIONS asks no selector.
        with self.assertNumQueries(0):
            self.client.options("/invoices/999/")


class ARefusalOfEachStatusTests(APITestCase):
    """How each refusal is answered."""

    def test_an_invalid_body_is_a_400_keyed_by_field(self) -> None:
        # A missing field and a mistyped one are refused together.
        response = self.client.post("/invoices/", {"amount_cents": "many"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(set(response.data), {"customer", "amount_cents"})

    def test_a_permission_check_refusing_is_a_403(self) -> None:
        invoice = _invoice()

        response = self.client.post(f"/invoices/{invoice.pk}/send/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_a_missing_row_is_a_404(self) -> None:
        self.assertEqual(self.client.get("/invoices/999/").status_code, status.HTTP_404_NOT_FOUND)
        response = self.client.patch("/invoices/999/", {"notes": "x"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_a_service_conflict_is_a_409(self) -> None:
        invoice = _invoice(status=Invoice.STATUS_SENT)

        response = self.client.patch(f"/invoices/{invoice.pk}/", {"notes": "late"})

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["detail"], "Only a draft invoice can be changed.")

    def test_any_other_service_error_is_a_422(self) -> None:
        user = User.objects.create_user("clerk")
        self.client.force_authenticate(user)
        invoice = _invoice(amount_cents=0)

        response = self.client.post(f"/invoices/{invoice.pk}/send/")

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(response.data["detail"], "An invoice for nothing cannot be sent.")


class DRFPermissionCheckTests(APITestCase):
    """One ``DRFPermissionCheck`` answers over HTTP and through the kernel's ``dispatch``."""

    def setUp(self) -> None:
        self.user = User.objects.create_user("clerk")
        self.invoice = _invoice()

    def test_over_http_an_authenticated_client_is_admitted(self) -> None:
        self.client.force_authenticate(self.user)

        response = self.client.post(f"/invoices/{self.invoice.pk}/send/")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["status"], Invoice.STATUS_SENT)

    def test_off_http_the_same_check_admits_a_user(self) -> None:
        result = dispatch(SEND_SPEC, principal=self.user, arguments={"pk": self.invoice.pk})

        self.assertEqual(result.value.status, Invoice.STATUS_SENT)

    def test_off_http_the_same_check_refuses_an_anonymous_principal(self) -> None:
        with self.assertRaises(NotPermitted):
            dispatch(SEND_SPEC, principal=AnonymousUser(), arguments={"pk": self.invoice.pk})

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.STATUS_DRAFT)


class SharedSerializerContextTests(APITestCase):
    """The input serializer writes a key the output serializer reads."""

    def test_a_warning_validate_wrote_is_rendered_in_the_answer(self) -> None:
        response = self.client.post("/invoices/", {"customer": "Acme", "amount_cents": 0})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["warnings"], ["The amount is zero."])

    def test_a_call_whose_validate_wrote_nothing_renders_none(self) -> None:
        response = self.client.post("/invoices/", {"customer": "Acme", "amount_cents": 1})

        self.assertEqual(response.data["warnings"], [])
