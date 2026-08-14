"""Baseline security response headers for the API origin.

The API answers with JSON, a Swagger UI, and the discovery documents. None of
those need to be sniffed, framed, or referred with a full URL, so the same
three headers the marketing origin already sends belong here too. HSTS is only
emitted for requests that actually arrived over TLS, so plain-HTTP local
development is unaffected and the header is never sent where a browser must
ignore it.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Two years, matching the marketing origin's vercel.json. "preload" is
# deliberately omitted: submitting to the preload list is a slow-to-reverse
# commitment for every subdomain and is an operator decision, not a default.
HSTS_VALUE = "max-age=63072000; includeSubDomains"

STATIC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach baseline security headers without overriding explicit values."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for header, value in STATIC_HEADERS.items():
            response.headers.setdefault(header, value)
        if _is_secure(request):
            response.headers.setdefault("Strict-Transport-Security", HSTS_VALUE)
        return response


def _is_secure(request: Request) -> bool:
    """Return whether the client reached the origin over HTTPS.

    Behind Railway's edge the app itself is spoken to over plain HTTP, so the
    forwarded scheme is what matters. ``request.url.scheme`` already reflects
    ``X-Forwarded-Proto`` when a proxy-headers middleware is installed; the
    explicit header check keeps the behaviour correct if it is not.
    """

    forwarded = request.headers.get("x-forwarded-proto", "")
    if forwarded:
        # A proxy chain sends a comma-separated list; the client-most hop leads.
        return forwarded.split(",")[0].strip().casefold() == "https"
    return request.url.scheme == "https"
