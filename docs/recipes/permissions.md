# DRF permission classes

A route is guarded twice, in order: the view's own `permission_classes`, which
DRF asks in `initial()` before any handler runs, and the spec's `permissions`,
which the kernel's `dispatch` asks. The view's classes guard the route; the
spec's guard the operation, wherever it is served.

## On the spec: `DRFPermissionCheck`

```python
from django_service_specs import ServiceSpec
from rest_framework.permissions import IsAuthenticated

from django_spec_rest.service_specs.drf_permission_check import DRFPermissionCheck

SEND_SPEC = ServiceSpec(
    service=send_invoice,
    instance_selector_spec=INVOICE_LOOKUP,
    permissions=(DRFPermissionCheck([IsAuthenticated]),),
    presenter=PRESENTER,
)
```

`DRFPermissionCheck` asks every class in order, a fresh instance each time, as
DRF's `get_permissions` does:

- **`has_permission`** against the request and view the call carries. A
  refusal raises `DRFNotPermitted` with that class's own `message` and
  `code`, which DRF answers 403. A class raising DRF's `NotAuthenticated`
  leaves as `DRFNotAuthenticated`, which DRF answers 401 where the
  authenticator supplies a challenge.
- **`has_object_permission`** of the row a write targets or a retrieve finds,
  when it is a model instance.
- The kernel's question about a set (a bulk call, a collection, a create)
  is allowed: DRF has no such question, and the class-level check has
  already run.

Each refusal is the kernel's `NotPermitted` as well, so a caller of the
kernel's `dispatch` catches it by the kernel's class.

## Off HTTP

The same check runs when the spec is dispatched with no request. It builds an
offline request and view for the principal (`build_offline_context`), so a
class reading `request.user` reads the principal, and `view.action` is the
call context's `action` where one is given. The offline request's query
string is empty.

A class scoping by a route capture reads `view.kwargs`, which off HTTP no
URLconf fills. Name those arguments in `route_reads`, and the check puts them
on the offline view's `kwargs` before asking:

```python
DRFPermissionCheck([IsProjectMember], route_reads=["project_pk"])
```

```python
from django_service_specs import NotPermitted, dispatch

dispatch(SEND_SPEC, principal=user, arguments={"pk": invoice.pk})  # runs
dispatch(SEND_SPEC, principal=AnonymousUser(), arguments={"pk": invoice.pk})  # NotPermitted
```

The example project asserts both, and the 403 over HTTP.

## A nested selector declares none

The specs on `instance_selector_spec`, `collection_selector_spec` and
`output_selector_spec` are never asked for their permissions: the spec being
served is what authorizes. `as_view()` refuses a nested selector that declares
`permissions`, so a check placed there cannot look like it guards something.
