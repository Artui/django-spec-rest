"""``permission_denied`` - the refusal DRF's ``APIView.permission_denied`` raises, as the kernel's denial."""

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

    The rule an adapted DRF class is answered by:
    [`DRFPermissionCheck`][django_spec_rest.service_specs.drf_permission_check.DRFPermissionCheck]
    raises it for a class answering ``False``. A kernel ``PermissionCheck``'s
    ``NotPermitted`` is not decided by it for now: the kernel raises the same
    bare class for a permission check's denial, a service's own and a refused
    inner dispatch's, so the kernel route answers all of them 403 with their
    message, and a caller nobody authenticated is not asked to sign in by one
    (``tests/views/test_an_anonymous_caller_refused.py``). An offline request
    has no authenticator, so off HTTP a refusal is always the denial.

    A request that is not DRF's has no ``authenticators`` and is read as having
    none, so a carried stand-in is refused as an offline request is.
    """
    # One arc to coverage, so each half is named: test_permission_denied's
    # test_off_http_a_refusal_is_the_denial fails without the first and
    # test_a_recognised_caller_is_denied_with_the_message_and_code without the second.
    if getattr(request, "authenticators", ()) and not request.successful_authenticator:
        return DRFNotAuthenticated()
    return DRFNotPermitted(message, code)
