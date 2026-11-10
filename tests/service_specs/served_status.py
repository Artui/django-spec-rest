from __future__ import annotations

from typing import Any

from django.core.handlers.exception import convert_exception_to_response
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView


def served_status(error: Exception) -> int:
    """The status Django answers when a DRF view raises ``error``."""

    class _Raising(APIView):
        authentication_classes: Any = []
        permission_classes: Any = []

        def get(self, request: Request) -> Response:
            raise error

    view = convert_exception_to_response(_Raising.as_view())
    return view(APIRequestFactory().get("/")).status_code
