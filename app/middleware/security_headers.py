"""Baseline security response headers for the API origin.

The API answers with JSON, a Swagger UI, and a few first-party HTML pages.
None of those need to be sniffed, framed, or referred with a full URL, so the
same three headers the marketing origin already sends belong here too. HSTS is
only emitted for requests that actually arrived over TLS, so plain-HTTP local
development is unaffected and the header is never sent where a browser must
ignore it.

Content-Security-Policy is path-aware: JSON has nothing to execute, first-party
HTML (dashboard, approval cards) is inline-CSS only, and FastAPI's stock
Swagger UI / ReDoc need jsDelivr plus an inline boot script. Cache-Control:
no-store is the default on tenant-sensitive paths; public discovery stays
cacheable so agents can keep OpenAPI and well-known documents.
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

# JSON and every non-HTML response: browsers should not execute anything here.
# frame-ancestors 'self' matches X-Frame-Options: SAMEORIGIN.
API_CSP = (
    "default-src 'none'; "
    "frame-ancestors 'self'; "
    "base-uri 'none'; "
    "form-action 'none'"
)

# Dashboard and permit-request cards: inline CSS, data: icons, no scripts.
FIRST_PARTY_HTML_CSP = (
    "default-src 'none'; "
    "script-src 'none'; "
    "style-src 'unsafe-inline'; "
    "img-src 'self' data:; "
    "frame-ancestors 'self'; "
    "base-uri 'none'; "
    "form-action 'none'"
)

# FastAPI ships Swagger UI / ReDoc from jsDelivr with an inline window.onload
# boot script and fetches /openapi.json from this origin. Restricted to the
# two documentation HTML paths so the JSON API stays locked down.
DOCS_HTML_CSP = (
    "default-src 'none'; "
    "script-src https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "frame-ancestors 'self'; "
    "base-uri 'none'; "
    "form-action 'none'"
)

_DOCS_HTML_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect"})

# Public discovery is intentionally credential-less and agent-cacheable.
# Everything else — wallets, permits, receipts, keys, invoke — is no-store.
_PUBLIC_DISCOVERY_PATHS = frozenset(
    {
        "/",
        "/docs",
        "/redoc",
        "/docs/oauth2-redirect",
        "/docs/index",
        "/openapi.json",
        "/health",
        "/health/ready",
        "/health/dependencies",
        "/llm.txt",
        "/llms.txt",
        "/WEDGE.md",
        "/SECURITY_LIMITATIONS.md",
        "/DESIGN_PARTNER_GUIDE.md",
        "/docs/partner-api-key-bootstrap.md",
        "/docs/agent-accountability.md",
        "/dashboard",
        "/v1/discover",
        "/mcp/tools.json",
        "/mcp/tools",
    }
)
_PUBLIC_DISCOVERY_PREFIXES = ("/.well-known/",)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach baseline security headers without overriding explicit values."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for header, value in STATIC_HEADERS.items():
            response.headers.setdefault(header, value)
        response.headers.setdefault(
            "Content-Security-Policy",
            _content_security_policy(request, response),
        )
        if not _is_public_discovery(request.url.path):
            response.headers.setdefault("Cache-Control", "no-store")
        if _is_secure(request):
            response.headers.setdefault("Strict-Transport-Security", HSTS_VALUE)
        return response


def _normalized_path(path: str) -> str:
    if path != "/":
        return path.rstrip("/") or "/"
    return path


def _content_security_policy(request: Request, response: Response) -> str:
    path = _normalized_path(request.url.path)
    if path in _DOCS_HTML_PATHS:
        return DOCS_HTML_CSP
    content_type = (
        response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    if content_type == "text/html":
        return FIRST_PARTY_HTML_CSP
    return API_CSP


def _is_public_discovery(path: str) -> bool:
    normalized = _normalized_path(path)
    if normalized in _PUBLIC_DISCOVERY_PATHS:
        return True
    return normalized.startswith(_PUBLIC_DISCOVERY_PREFIXES)


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
