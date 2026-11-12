from __future__ import annotations

from typing import Any

from django_spec_rest.service_specs.drf_not_authenticated import DRFNotAuthenticated
from django_spec_rest.service_specs.drf_not_permitted import DRFNotPermitted


def permission_denied(
    request: Any, message: str | None = None, code: str | None = None
) -> DRFNotAuthenticated | DRFNotPermitted:
    """The refusal of a caller ``request`` carries, decided as DRF's view decides it.

    A request whose authenticators recognised nobody is
    [`DRFNotAuthenticated`][django_spec_rest.service_specs.drf_not_authenticated.DRFNotAuthenticated],
    with DRF's wording, which the view answers 401 with the first
    authenticator's ``WWW-Authenticate``, or 403 where that authenticator gives
    no header. Any other, a request with no authenticator at all among them, is
    [`DRFNotPermitted`][django_spec_rest.service_specs.drf_not_permitted.DRFNotPermitted]
    with ``message`` and ``code``, 403. So a permission's ``message`` reaches
    only a caller who is signed in or could not have been, as in DRF.

    The rule every permission check the spec declares is answered by:
    [`DRFPermissionCheck`][django_spec_rest.service_specs.drf_permission_check.DRFPermissionCheck]
    raises it for a class answering ``False``, and the kernel route answers
    with it a kernel ``PermissionCheck``'s denial, which the kernel marks as
    ``PermissionCheckDenied``, where the denied spec is the one the route
    dispatched. A service's own ``NotPermitted``, and a refused inner
    dispatch's, are not decided by it: they stay 403 with their message
    (``tests/views/test_an_anonymous_caller_refused.py``). An offline request
    has no authenticator, so off HTTP a refusal is always the denial.

    A request that is not DRF's has no ``authenticators`` and is read as having
    none, so a carried stand-in is refused as an offline request is.
    """
    if getattr(request, "authenticators", ()) and not request.successful_authenticator:
        return DRFNotAuthenticated()
    return DRFNotPermitted(message, code)
