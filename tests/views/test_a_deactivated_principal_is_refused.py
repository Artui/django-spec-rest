"""A deactivated user acting through a live view over a kernel spec is refused with a 403.

The kernel refuses a principal whose ``is_active`` is false before any
permission check runs, so a view declaring no ``permission_classes`` at all
refuses it too. The refusal is ``DRFPrincipalUnavailable``:
``{"detail": "The acting principal is unavailable."}``, code
``permission_denied``. The same user, active, is served, so each test holds the
flag rather than the view.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django_service_specs import (
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    Unrestricted,
)
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from django_spec_rest import (
    SelectorRetrieveView,
    ServiceCreateView,
    ServiceDeleteView,
    ServiceUpdateView,
    ServiceViewSet,
)
from django_spec_rest.dispatch.kernel_edge import adispatch_kernel_spec
from django_spec_rest.service_specs.drf_principal_unavailable import DRFPrincipalUnavailable
from django_spec_rest.service_specs.serializer_presenter import SerializerPresenter
from django_spec_rest.service_specs.serializer_validator import SerializerValidator
from django_spec_rest.views.utils import view_call_context
from tests.testapp.models import Author
from tests.testapp.serializers import AuthorSerializer

pytestmark = pytest.mark.django_db

_factory = APIRequestFactory()
_UNAVAILABLE = {"detail": "The acting principal is unavailable."}
_ACTIVE = pytest.mark.parametrize("active", [True, False], ids=["active", "deactivated"])
_OPEN = (Unrestricted(),)

# A gap in a file this module does not own, a strict xfail naming it.
_VIEWSET_GAP = pytest.mark.xfail(
    strict=True,
    reason="ServiceViewSet.action_specs refuses a kernel ServiceSpec at as_view()",
)

ran: list[str] = []


@pytest.fixture(autouse=True)
def _forget_runs() -> None:
    ran.clear()


def _user(active: bool) -> Any:
    return get_user_model().objects.create_user(username="u", is_active=active)


def _as(request: Any, active: bool) -> Any:
    force_authenticate(request, user=_user(active))
    return request


def _create(*, data: Any) -> Author:
    ran.append("create")
    return Author.objects.create(name=data["name"])


def _update(*, instance: Author, data: Any) -> Author:
    ran.append("update")
    instance.name = data["name"]
    instance.save()
    return instance


def _delete(*, instance: Author) -> None:
    ran.append("delete")
    instance.delete()


async def _acreate(*, data: Any) -> Author:
    ran.append("acreate")
    return await Author.objects.acreate(name=data["name"])


def _read(*, pk: int) -> Any:
    ran.append("read")
    return Author.objects.filter(pk=pk).first()


_BY_PK = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, pk: Author.objects.filter(pk=pk).first(),
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
)


def _writes(service: Any, **fields: Any) -> ServiceSpec:
    return ServiceSpec(
        service=service,
        permissions=_OPEN,
        validator=SerializerValidator(AuthorSerializer),
        presenter=SerializerPresenter(AuthorSerializer),
        **fields,
    )


class _ViewPermissions:
    """The view's own ``permission_classes`` answer for a kernel spec.

    ``MutationFlowMixin.get_permissions`` reads a drfs spec's
    ``permission_classes``, which a kernel spec has no attribute for.
    """

    permission_classes: Any = []

    def get_permissions(self) -> list[Any]:
        return [permission() for permission in self.permission_classes]


class _Create(_ViewPermissions, ServiceCreateView):
    spec = _writes(_create)


class _ACreate(_ViewPermissions, ServiceCreateView):
    spec = _writes(_acreate)


class _Update(_ViewPermissions, ServiceUpdateView):
    queryset = Author.objects.all()
    spec = _writes(_update, instance_selector_spec=_BY_PK)


class _Delete(_ViewPermissions, ServiceDeleteView):
    queryset = Author.objects.all()
    spec = ServiceSpec(service=_delete, permissions=_OPEN, instance_selector_spec=_BY_PK)


class _Retrieve(SelectorRetrieveView):
    permission_classes: Any = []
    serializer_class = AuthorSerializer
    spec = SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=_read,
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
        permissions=_OPEN,
    )


class _ViewSet(_ViewPermissions, ServiceViewSet):
    queryset = Author.objects.all()
    action_specs = {"create": _writes(_create)}


def _answered(response: Any, active: bool, status: int, service: str) -> None:
    if active:
        assert response.status_code == status, response.data
        assert ran == [service]
    else:
        assert response.status_code == 403
        assert response.data == _UNAVAILABLE
        assert response.data["detail"].code == "permission_denied"
        assert ran == []


@_ACTIVE
def test_a_create_view_with_no_permission_classes(active: bool) -> None:
    request = _as(_factory.post("/", {"name": "n"}, format="json"), active)
    _answered(_Create.as_view()(request), active, 201, "create")


@_ACTIVE
def test_an_async_service_behind_a_create_view(active: bool) -> None:
    request = _as(_factory.post("/", {"name": "n"}, format="json"), active)
    _answered(_ACreate.as_view()(request), active, 201, "acreate")


@_ACTIVE
def test_an_update_view_with_no_permission_classes(active: bool) -> None:
    author = Author.objects.create(name="a")
    request = _as(_factory.put("/", {"name": "n"}, format="json"), active)
    _answered(_Update.as_view()(request, pk=author.pk), active, 200, "update")


@_ACTIVE
def test_a_delete_view_with_no_permission_classes(active: bool) -> None:
    author = Author.objects.create(name="a")
    request = _as(_factory.delete("/"), active)
    _answered(_Delete.as_view()(request, pk=author.pk), active, 204, "delete")


@_ACTIVE
def test_a_retrieve_view_with_no_permission_classes(active: bool) -> None:
    author = Author.objects.create(name="a")
    request = _as(_factory.get("/"), active)
    _answered(_Retrieve.as_view()(request, pk=author.pk), active, 200, "read")


@_VIEWSET_GAP
@_ACTIVE
def test_a_viewset_action_with_no_permission_classes(active: bool) -> None:
    request = _as(_factory.post("/", {"name": "n"}, format="json"), active)
    _answered(_ViewSet.as_view({"post": "create"})(request), active, 201, "create")


@pytest.mark.django_db(transaction=True)
async def test_the_async_core_refuses_it_on_a_live_view() -> None:
    user = await get_user_model().objects.acreate(username="u", is_active=False)
    view = ServiceCreateView()
    view.request = Request(_factory.post("/", {"name": "n"}, format="json"), parsers=[JSONParser()])
    view.request.user = user
    view.args, view.kwargs, view.format_kwarg = (), {}, None

    with pytest.raises(DRFPrincipalUnavailable):
        await adispatch_kernel_spec(
            _writes(_acreate),
            view=view,
            request=view.request,
            call_context=view_call_context(view, view.request),
        )
    assert ran == []
