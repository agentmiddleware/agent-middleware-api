"""Baseline response-hardening headers on the API origin."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.middleware.security_headers import HSTS_VALUE, SecurityHeadersMiddleware


def _client() -> TestClient:
    app = Starlette(routes=[Route("/probe", lambda request: PlainTextResponse("ok"))])
    app.add_middleware(SecurityHeadersMiddleware)
    return TestClient(app)


def test_baseline_headers_are_always_present() -> None:
    response = _client().get("/probe")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_hsts_is_sent_only_for_requests_that_arrived_over_tls() -> None:
    """A browser ignores HSTS over plain HTTP, so do not claim it there."""

    client = _client()

    plain = client.get("/probe")
    assert "strict-transport-security" not in plain.headers

    forwarded_http = client.get("/probe", headers={"x-forwarded-proto": "http"})
    assert "strict-transport-security" not in forwarded_http.headers

    # A proxy chain sends a comma-separated list; the client-most hop leads.
    forwarded_https = client.get("/probe", headers={"x-forwarded-proto": "https, http"})
    assert forwarded_https.headers["strict-transport-security"] == HSTS_VALUE


def test_hsts_does_not_claim_preload() -> None:
    """Preload is a slow-to-reverse, whole-subdomain-tree operator decision."""

    assert "preload" not in HSTS_VALUE
    assert "includeSubDomains" in HSTS_VALUE


def test_explicit_route_headers_are_not_overridden() -> None:
    app = Starlette(
        routes=[
            Route(
                "/framed",
                lambda request: PlainTextResponse(
                    "ok", headers={"X-Frame-Options": "DENY"}
                ),
            )
        ]
    )
    app.add_middleware(SecurityHeadersMiddleware)

    assert TestClient(app).get("/framed").headers["x-frame-options"] == "DENY"


def test_middleware_is_registered_on_the_application() -> None:
    from app.main import app

    assert any(entry.cls is SecurityHeadersMiddleware for entry in app.user_middleware)
