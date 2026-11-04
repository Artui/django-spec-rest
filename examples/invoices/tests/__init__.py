"""End-to-end tests of the example: one class per behaviour the README lists."""

from __future__ import annotations

import base64

from django.contrib.auth.models import AnonymousUser, User
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import DEFAULT_POOL_SEEDS, NotPermitted, dispatch
from drf_spectacular.generators import SchemaGenerator
from rest_framework import status
from rest_framework.test import APITestCase

from invoices.models import Invoice
from invoices.views import (
    LIST_SPEC,
    SEEDS,
    SEND_SPEC,
    UPDATE_SPEC,
    InvoiceViewSet,
    ReviewInvoiceListView,
)


def _basic(username: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


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

    def test_a_patch_body_naming_the_lookup_key_cannot_move_the_update(self) -> None:
        """The row an update reaches is read from the route alone: a ``pk`` in
        the body is dropped, never the update's lookup."""
        routed, other = _invoice(), _invoice(customer="Globex")

        response = self.client.patch(
            f"/invoices/{routed.pk}/", {"notes": "Net 30", "pk": other.pk}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["id"], routed.pk)
        routed.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(routed.notes, "Net 30")
        self.assertEqual(other.notes, "")

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
        result = dispatch(
            SEND_SPEC, principal=self.user, arguments={"pk": self.invoice.pk}, pool_seeds=SEEDS
        )

        self.assertEqual(result.value.status, Invoice.STATUS_SENT)

    def test_off_http_the_same_check_refuses_an_anonymous_principal(self) -> None:
        with self.assertRaises(NotPermitted):
            dispatch(
                SEND_SPEC,
                principal=AnonymousUser(),
                arguments={"pk": self.invoice.pk},
                pool_seeds=SEEDS,
            )

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.STATUS_DRAFT)


class AnAnonymousCallerRefusedTests(APITestCase):
    """An adapted DRF class refusing a caller nobody recognised asks them to sign in.

    ``/staff-invoices/`` authenticates with ``BasicAuthentication`` and guards
    its spec with a ``DRFPermissionCheck``. The project's own settings name no
    authenticator, so ``/invoices/<pk>/send/`` answers an anonymous caller 403.
    """

    def test_an_anonymous_caller_is_a_401_carrying_the_challenge(self) -> None:
        response = self.client.get("/staff-invoices/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response["WWW-Authenticate"], 'Basic realm="api"')

    def test_a_signed_in_caller_the_class_refuses_is_a_403_with_its_message(self) -> None:
        User.objects.create_user("clerk", password="s3cret")
        self.client.credentials(HTTP_AUTHORIZATION=_basic("clerk", "s3cret"))

        response = self.client.get("/staff-invoices/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["detail"], "Only staff can list every invoice.")
        self.assertNotIn("WWW-Authenticate", response)

    def test_a_signed_in_caller_the_class_admits_is_answered(self) -> None:
        User.objects.create_user("boss", password="s3cret", is_staff=True)
        _invoice()
        self.client.credentials(HTTP_AUTHORIZATION=_basic("boss", "s3cret"))

        response = self.client.get("/staff-invoices/")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(len(response.data), 1)


class AKernelCheckRefusedTests(APITestCase):
    """A kernel ``PermissionCheck`` refusing a caller nobody recognised asks them to sign in.

    ``/audited-invoices/`` is ``/staff-invoices/`` with the guard written as the
    kernel's own ``PermissionCheck`` (``IsSuperuser``) rather than an adapted DRF
    class, and the answers are the same.
    """

    def test_an_anonymous_caller_is_a_401_carrying_the_challenge(self) -> None:
        response = self.client.get("/audited-invoices/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response["WWW-Authenticate"], 'Basic realm="api"')

    def test_a_signed_in_caller_the_check_refuses_is_a_403_with_its_message(self) -> None:
        User.objects.create_user("clerk", password="s3cret", is_staff=True)
        self.client.credentials(HTTP_AUTHORIZATION=_basic("clerk", "s3cret"))

        response = self.client.get("/audited-invoices/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["detail"], "Only a superuser can list the audited invoices.")
        self.assertNotIn("WWW-Authenticate", response)

    def test_a_signed_in_caller_the_check_admits_is_answered(self) -> None:
        User.objects.create_superuser("root", password="s3cret")
        _invoice()
        self.client.credentials(HTTP_AUTHORIZATION=_basic("root", "s3cret"))

        response = self.client.get("/audited-invoices/")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(len(response.data), 1)


class OpenAPISchemaTests(APITestCase):
    """The project generates its schema the documented way.

    drf-spectacular's ``AutoSchema`` is the project's default schema class and
    ``InvoicesConfig.ready()`` calls ``enable_openapi()``. Each test names the
    statuses it needs and asserts they are present, never the whole set: the
    schema may document more as the package learns to.
    """

    def setUp(self) -> None:
        self.schema = SchemaGenerator().get_schema(request=None, public=True)

    def _body_component(self, path: str, method: str, code: str) -> str:
        response = self.schema["paths"][path][method]["responses"][code]
        return response["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]

    def test_a_permission_checked_route_documents_its_403(self) -> None:
        self.assertEqual(
            self._body_component("/invoices/{id}/send/", "post", "403"), "PermissionDenied"
        )

    def test_a_route_with_a_challenging_authenticator_documents_its_401_and_403(self) -> None:
        # ``BasicAuthentication`` sends a challenge, so the refusal of a caller
        # nobody authenticated is the 401 the route answers (see
        # ``AnAnonymousCallerRefusedTests``).
        self.assertEqual(self._body_component("/staff-invoices/", "get", "401"), "NotAuthenticated")
        self.assertEqual(self._body_component("/staff-invoices/", "get", "403"), "PermissionDenied")

    def test_a_route_guarded_by_a_kernel_check_documents_its_401_and_403(self) -> None:
        # The kernel's ``PermissionCheck`` is answered as the adapted DRF class
        # is (see ``AKernelCheckRefusedTests``), so the schema says so.
        self.assertEqual(
            self._body_component("/audited-invoices/", "get", "401"), "NotAuthenticated"
        )
        self.assertEqual(
            self._body_component("/audited-invoices/", "get", "403"), "PermissionDenied"
        )

    def test_a_refusal_the_service_raises_is_documented_where_it_is_declared(self) -> None:
        # ``update_invoice`` raises ``ServiceConflict``; only ``@extend_schema``
        # on the viewset's update and partial update declares it.
        for method in ("put", "patch"):
            with self.subTest(method=method):
                self.assertEqual(
                    self._body_component("/invoices/{id}/", method, "409"), "ServiceConflict"
                )

    def test_a_view_level_permission_class_declares_the_exported_bodies(self) -> None:
        # The spec admits everyone, so these are the project's own declaration
        # (``@extend_schema`` with the exported serializers), and each is the
        # package's component rather than a new one beside it.
        self.assertEqual(
            self._body_component("/review-invoices/", "get", "401"), "NotAuthenticated"
        )
        self.assertEqual(
            self._body_component("/review-invoices/", "get", "403"), "PermissionDenied"
        )
        # Those statuses are the view's declaration, not the spec's: the spec
        # admits everyone, and the declared descriptions win over a spec's own.
        responses = self.schema["paths"]["/review-invoices/"]["get"]["responses"]
        self.assertEqual(responses["401"]["description"], "No credentials were sent.")
        self.assertEqual(responses["403"]["description"], "The caller is not staff.")
        self.assertNotIn("403", self.schema["paths"]["/invoices/"]["get"]["responses"])
        self.assertIs(ReviewInvoiceListView.spec, LIST_SPEC)

    def test_a_viewset_of_a_mixin_before_generic_viewset_documents_its_spec_s_bodies(self) -> None:
        # ``DraftInvoiceViewSet`` sets no ``schema``: it inherits the mixin's.
        operation = self.schema["paths"]["/drafts/"]["post"]
        body = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        self.assertEqual(body.rsplit("/", 1)[-1], "InvoiceInput")
        self.assertEqual(self._body_component("/drafts/", "post", "201"), "Invoice")
        self.assertIn("400", operation["responses"])
        # The same bodies the full viewset's create documents from the same spec.
        created = self.schema["paths"]["/invoices/"]["post"]
        self.assertEqual(operation["requestBody"], created["requestBody"])
        self.assertEqual(operation["responses"]["201"], created["responses"]["201"])


class SharedSerializerContextTests(APITestCase):
    """The input serializer writes a key the output serializer reads."""

    def test_a_warning_validate_wrote_is_rendered_in_the_answer(self) -> None:
        response = self.client.post("/invoices/", {"customer": "Acme", "amount_cents": 0})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["warnings"], ["The amount is zero."])

    def test_a_call_whose_validate_wrote_nothing_renders_none(self) -> None:
        response = self.client.post("/invoices/", {"customer": "Acme", "amount_cents": 1})

        self.assertEqual(response.data["warnings"], [])


class ASeedTheViewSetRegistersTests(APITestCase):
    """``InvoiceViewSet.pool_seeds`` hands ``sending_paused`` to the send spec's condition."""

    def setUp(self) -> None:
        self.client.force_authenticate(User.objects.create_user("clerk"))
        self.invoice = _invoice()

    def test_while_sending_is_paused_the_send_is_a_409(self) -> None:
        with self.settings(INVOICES_SENDING_PAUSED=True):
            response = self.client.post(f"/invoices/{self.invoice.pk}/send/")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "sending_paused")
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.STATUS_DRAFT)

    def test_otherwise_the_invoice_is_sent(self) -> None:
        response = self.client.post(f"/invoices/{self.invoice.pk}/send/")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_a_viewset_not_registering_it_is_refused_at_as_view(self) -> None:
        """The decorated action's seeds are the viewset's, checked at mount."""
        with self.assertRaisesRegex(
            ImproperlyConfigured, r"InvoiceViewSet\.send: .*sending_paused"
        ):
            InvoiceViewSet.as_view({"post": "send"}, pool_seeds=DEFAULT_POOL_SEEDS)


class AViewLevelPermissionClassRefusedTests(APITestCase):
    """The refusals ``ReviewInvoiceListView`` declares are the ones it answers."""

    def test_an_anonymous_caller_is_a_401_carrying_the_challenge(self) -> None:
        response = self.client.get("/review-invoices/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.headers["WWW-Authenticate"], 'Basic realm="api"')

    def test_a_signed_in_caller_who_is_not_staff_is_a_403_with_the_class_s_message(self) -> None:
        User.objects.create_user("member", password="pw")
        response = self.client.get("/review-invoices/", HTTP_AUTHORIZATION=_basic("member", "pw"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["detail"], "Only staff can open the review queue.")

    def test_a_staff_caller_is_answered(self) -> None:
        User.objects.create_user("clerk", password="pw", is_staff=True)
        _invoice()
        response = self.client.get("/review-invoices/", HTTP_AUTHORIZATION=_basic("clerk", "pw"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(len(response.data), 1)


class AMixinViewSetTests(APITestCase):
    """``DraftInvoiceViewSet``: the create mixin over ``GenericViewSet`` serves its spec."""

    def test_a_create_is_validated_and_presented_by_the_spec(self) -> None:
        response = self.client.post("/drafts/", {"customer": "Acme", "amount_cents": 4200})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["customer"], "Acme")
        self.assertEqual(Invoice.objects.count(), 1)

    def test_only_the_actions_it_composes_are_routed(self) -> None:
        self.assertEqual(
            self.client.get("/drafts/").status_code, status.HTTP_405_METHOD_NOT_ALLOWED
        )
        # A row that exists, so a 404 is the absent route and not a missing row.
        row = _invoice()
        self.assertEqual(
            self.client.get(f"/drafts/{row.pk}/").status_code, status.HTTP_404_NOT_FOUND
        )
