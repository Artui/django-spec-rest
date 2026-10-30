"""Services: plain callables, refusing with the kernel's framework-agnostic errors."""

from __future__ import annotations

from typing import Any

from django_service_specs import ServiceConflict, ServiceError

from invoices.models import Invoice


def create_invoice(*, data: dict[str, Any]) -> Invoice:
    return Invoice.objects.create(**data)


def update_invoice(*, instance: Invoice, data: dict[str, Any]) -> Invoice:
    if instance.status != Invoice.STATUS_DRAFT:
        # 409: the request is well formed, but the row's state forbids it.
        raise ServiceConflict("Only a draft invoice can be changed.")
    for name, value in data.items():
        setattr(instance, name, value)
    instance.save()
    return instance


def send_invoice(*, instance: Invoice) -> Invoice:
    if instance.amount_cents == 0:
        # 422: any other ``ServiceError``.
        raise ServiceError("An invoice for nothing cannot be sent.")
    instance.status = Invoice.STATUS_SENT
    instance.save(update_fields=["status", "updated_at"])
    return instance
