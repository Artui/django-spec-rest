from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import urlsplit

from django.http import HttpRequest, QueryDict
from rest_framework.request import Request

from django_spec_rest.types.offline_context import OfflineContext
from django_spec_rest.types.offline_http_request import OfflineHttpRequest
from django_spec_rest.types.offline_service_view import OfflineServiceView


def build_offline_context(
    user: Any,
    params: Mapping[str, Any] | list[Any] | None = None,
    *,
    http_request: HttpRequest | None = None,
    action: str | None = None,
    kwargs: Mapping[str, Any] | None = None,
    query_params: Mapping[str, Any] | None = None,
    host: str | None = None,
) -> OfflineContext:
    """Build the [`OfflineContext`][django_spec_rest.types.offline_context.OfflineContext] for dispatching a spec outside an HTTP request."""
    base: HttpRequest = (
        _copy_request(http_request) if http_request is not None else _synthesize_request(host)
    )
    base.method = "POST"
    if query_params is not None:
        base.GET = _build_query_dict(query_params)  # ty: ignore[invalid-assignment]
    raw: Any = Request(base)
    drf_request: Request = cast(Request, raw)
    drf_request.user = user
    drf_request.auth = None
    drf_request._authenticator = None  # ty: ignore[unresolved-attribute]
    drf_request._full_data = params if params is not None else {}  # ty: ignore[unresolved-attribute]
    view = OfflineServiceView(
        request=drf_request, action=action, kwargs=dict(kwargs) if kwargs is not None else {}
    )
    return OfflineContext(user=user, request=drf_request, view=view)


def _copy_request(http_request: HttpRequest) -> HttpRequest:
    """Shallow-copy the caller's request so the derived one owns its own attributes."""
    clone: Any = object.__new__(type(http_request))
    clone.__dict__.update(http_request.__dict__)
    return cast(HttpRequest, clone)


def _synthesize_request(host: str | None) -> OfflineHttpRequest:
    """Build the hostless-by-default stand-in, seeding ``META`` when a host is given."""
    raw: Any = OfflineHttpRequest()
    request: OfflineHttpRequest = cast(OfflineHttpRequest, raw)
    if host is None:
        return request
    scheme, netloc = _split_host(host)
    hostname, _, port = netloc.partition(":")
    request.offline_host = netloc
    request.META["HTTP_HOST"] = netloc
    request.META["SERVER_NAME"] = hostname
    request.META["SERVER_PORT"] = port or ("443" if scheme == "https" else "80")
    request.META["wsgi.url_scheme"] = scheme
    return request


def _split_host(host: str) -> tuple[str, str]:
    """Split ``host`` into ``(scheme, netloc)``, defaulting the scheme to ``http``."""
    if "//" not in host:
        return ("http", host.strip("/"))
    split = urlsplit(host)
    return (split.scheme or "http", split.netloc)


def _build_query_dict(query_params: Mapping[str, Any]) -> QueryDict:
    """Build an immutable ``QueryDict`` from a mapping, mirroring an HTTP ``GET``."""
    query_dict = QueryDict(mutable=True)
    for key, value in query_params.items():
        if isinstance(value, (list, tuple)):
            query_dict.setlist(key, [str(item) for item in value])
        else:
            query_dict[key] = str(value)
    query_dict._mutable = False
    return query_dict
