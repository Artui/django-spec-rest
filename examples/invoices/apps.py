"""App config for the invoices example app."""

from __future__ import annotations

from django.apps import AppConfig


class InvoicesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "invoices"

    def ready(self) -> None:
        # Documents each library view's spec for drf-spectacular. It runs once
        # the app registry is loaded, before the URLconf imports the views.
        from django_spec_rest.openapi import enable_openapi

        enable_openapi()
