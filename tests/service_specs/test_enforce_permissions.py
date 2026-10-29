"""DRF permission classes enforced on a kernel spec, by the kernel's own ``dispatch``.

drfs' ``enforce_permissions`` asked a spec's ``permission_classes`` against a
context the caller built. A kernel spec declares the same classes as a
``DRFPermissionCheck`` in its ``permissions``, and the kernel asks them: the
class-level check always, the object check only of a model row. The cases
``test_drf_permission_check`` already holds - a refusal's message and code,
the first refusing class answering, a create or a collection never asked about
an object, a target that is no model - are not repeated here.

What changes by design: drfs refused a context with no request by name, as
``ImproperlyConfigured``, because DRF would otherwise raise ``AttributeError``
from inside the caller's class. A kernel call never reaches a class without a
request, since the check builds the offline pair for whatever the call lacks,
so a call with no ``call_context`` at all is answered rather than refused.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.models import User
from django_service_specs import SelectorKind, SelectorSpec, ServiceSpec
from django_service_specs.dispatch.dispatch import dispatch
from rest_framework.permissions import BasePermission, IsAdminUser

from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck
from django_spec_rest.service_specs.not_permitted import NotPermitted
from tests.testapp.models import Tag

pytestmark = pytest.mark.django_db


class _DenyRequest(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return False


class _DenyObject(BasePermission):
    def has_object_permission(self, request: Any, view: Any, obj: Any) -> bool:
        return False


class _Buggy(BasePermission):
    def has_permission(self, request: Any, view: Any) -> bool:
        return request.no_such_attribute


def _every_tag(*classes: type[BasePermission]) -> ServiceSpec:
    """A service over every tag, ``classes`` asked about the collection it resolves.

    The classes are the service's own, asked by the kernel about the target
    it resolved for the spec being dispatched.
    """
    return ServiceSpec(
        service=lambda *, collection: collection.count(),
        collection_selector_spec=SelectorSpec(
            kind=SelectorKind.LIST,
            selector=lambda: Tag.objects.all(),
            permissions=(DRFPermissionCheck(()),),
        ),
        permissions=(DRFPermissionCheck(classes),),
    )


def test_no_classes_admits_every_call() -> None:
    spec = ServiceSpec(service=lambda: "ran", permissions=(DRFPermissionCheck(()),))

    assert dispatch(spec, principal=User(), arguments={}).value == "ran"


def test_a_collection_target_is_never_asked_about_an_object() -> None:
    Tag.objects.create(name="a")

    assert dispatch(_every_tag(_DenyObject), principal=User(), arguments={}).value == 1


def test_the_class_level_check_still_refuses_a_collection_target() -> None:
    with pytest.raises(NotPermitted):
        dispatch(_every_tag(_DenyRequest), principal=User(), arguments={})


@pytest.mark.parametrize(("is_staff", "admitted"), [(True, True), (False, False)])
def test_a_call_with_no_call_context_is_answered_rather_than_refused(
    is_staff: bool, admitted: bool
) -> None:
    spec = ServiceSpec(service=lambda: "ran", permissions=(DRFPermissionCheck((IsAdminUser,)),))
    principal = User.objects.create(username="u", is_staff=is_staff)

    if admitted:
        assert dispatch(spec, principal=principal, arguments={}).value == "ran"
    else:
        with pytest.raises(NotPermitted):
            dispatch(spec, principal=principal, arguments={})


def test_an_attribute_error_a_class_raises_is_its_own() -> None:
    spec = ServiceSpec(service=lambda: "ran", permissions=(DRFPermissionCheck((_Buggy,)),))

    with pytest.raises(AttributeError, match="no_such_attribute"):
        dispatch(spec, principal=User(), arguments={})
