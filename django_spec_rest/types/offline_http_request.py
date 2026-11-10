from __future__ import annotations

from django.http import HttpRequest


class OfflineHttpRequest(HttpRequest):
    """An ``HttpRequest`` with no ambient host, made safe to use."""

    offline_host: str | None = None
    """The configured host (``"example.com"`` / ``"example.com:8000"``), or
    ``None`` when the caller didn't configure one. Set by
    [`build_offline_context`][django_spec_rest.service_specs.build_offline_context.build_offline_context];
    when it is set, ``META`` carries the matching keys and Django's own
    machinery is in charge, so nothing on this class changes behaviour."""

    def build_absolute_uri(self, location: str | None = None) -> str:
        """Absolute URI when a host is configured; the location itself when not."""
        if self.offline_host is not None:
            return super().build_absolute_uri(location)
        if location is None:
            return self.get_full_path()
        return location

    def _get_scheme(self) -> str:
        """Read the scheme from ``META``, as ``WSGIRequest`` does."""
        return str(self.META.get("wsgi.url_scheme", "http"))

    def get_host(self) -> str:
        """The configured host verbatim; a pointed error when there is none."""
        if self.offline_host is not None:
            return self.offline_host
        raise ValueError(
            "This request was synthesized off the HTTP path and has no host. "
            "Pass build_offline_context(host='example.com') (or "
            "host='https://example.com') to give it one — e.g. from your Sites "
            "framework entry, or a project setting naming your public origin. "
            "Without a host, build_absolute_uri() returns relative URLs instead "
            "of raising."
        )


__all__ = ["OfflineHttpRequest"]
