"""A view's ``get_progress_reporter`` hook reaches a kernel spec's service as ``progress``.

A project tracking a long-running job (a task writing to a workflow model, a
view pushing to a websocket) supplies its own reporter through the view's
``get_progress_reporter`` hook, which joins the call's reporter.

``progress`` is a pool seed. drfs dropped a ``get_service_kwargs`` value of that
name silently and the service reported into the no-op. The kernel refuses it
instead, as ``ImproperlyConfigured`` raised per request, because a provider's
value must never outrank a seeded one (the kernel's rule for any key a call
seeds itself, ``view`` among them). The reporter comes only through the progress
hook.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django_service_specs import ProgressReporter, ServiceSpec, Unrestricted, null_progress
from rest_framework.test import APIRequestFactory

from tests.views.test_kernel_views import _CreateView

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()


def _post(spec: ServiceSpec, **hooks: Any) -> Any:
    view = type("_View", (_CreateView,), {"spec": spec, **hooks}).as_view()
    return view(_factory.post("/", {}, format="json"))


def test_an_http_view_supplies_a_reporter_through_its_progress_hook() -> None:
    seen: list[tuple[float, float | None, str | None]] = []

    def slow_export(*, progress: ProgressReporter) -> dict[str, Any]:
        progress(1, total=2, message="working")
        return {"ok": True}

    def get_progress_reporter(self: Any) -> ProgressReporter:
        # Whatever this project already has: a websocket group send, a workflow-model
        # row, a Celery ``update_state``.
        return lambda p, *, total=None, message=None: seen.append((p, total, message))

    response = _post(
        ServiceSpec(service=slow_export, permissions=(Unrestricted(),), atomic=False),
        get_progress_reporter=get_progress_reporter,
    )

    assert response.status_code == 201, response.data
    assert seen == [(1, 2, "working")]


def test_a_service_with_no_progress_hook_reports_into_the_no_op() -> None:
    handed: list[Any] = []

    def slow_export(*, progress: ProgressReporter) -> dict[str, Any]:
        handed.append(progress)
        progress(1, total=2, message="working")
        return {"ok": True}

    response = _post(ServiceSpec(service=slow_export, permissions=(Unrestricted(),), atomic=False))

    assert response.status_code == 201, response.data
    assert handed == [null_progress]


def test_a_reporter_returned_by_get_service_kwargs_is_refused_not_dropped() -> None:
    shadowed: list[Any] = []
    ran: list[Any] = []

    def slow_export(*, progress: ProgressReporter) -> dict[str, Any]:
        ran.append(progress)
        return {"ok": True}

    def get_service_kwargs(self: Any) -> dict[str, Any]:
        return {"progress": lambda *args, **kwargs: shadowed.append(args)}

    with pytest.raises(ImproperlyConfigured, match=r"\['progress'\].*dispatch seeds itself"):
        _post(
            ServiceSpec(service=slow_export, permissions=(Unrestricted(),), atomic=False),
            get_service_kwargs=get_service_kwargs,
        )

    assert (ran, shadowed) == ([], [])
