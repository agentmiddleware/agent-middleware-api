"""Documented rate-limit threshold: 120/min, 429 on the 121st request.

A 40-request burst drawing zero 429s is the intended posture, not a missing
limiter. Auth-gated paths are counted. Discovery/docs/health are exempt.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core.rate_limiter import RateLimitMiddleware, rate_limit_discovery


def test_discovery_payload_matches_the_documented_120_default(monkeypatch) -> None:
    from app.core import rate_limiter as rate_limiter_module

    fake = type("Settings", (), {"RATE_LIMIT_PER_MINUTE": 120})()
    monkeypatch.setattr(rate_limiter_module, "get_settings", lambda: fake)

    payload = rate_limit_discovery()
    assert payload["requests_per_minute"] == 120
    assert payload["window_seconds"] == 60
    assert payload["burst_allowance"] == 0
    assert payload["unauthenticated_scope"] == "shared_anonymous_bucket"


@pytest.mark.anyio
async def test_forty_requests_do_not_429_at_the_documented_120_limit() -> None:
    """Reviewer burst of 40 against an auth-gated path: remaining drops, no 429."""

    async def ok(_request):
        return PlainTextResponse("ok")

    starlette_app = Starlette(routes=[Route("/v1/wallets", ok)])
    limited = RateLimitMiddleware(starlette_app, requests_per_minute=120)
    transport = ASGITransport(app=limited)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        responses = [
            await http.get("/v1/wallets", headers={"X-API-Key": "reviewer-key"})
            for _ in range(40)
        ]

    assert all(response.status_code == 200 for response in responses)
    assert responses[0].headers["X-RateLimit-Limit"] == "120"
    assert responses[0].headers["X-RateLimit-Remaining"] == "119"
    assert responses[-1].headers["X-RateLimit-Remaining"] == "80"


@pytest.mark.anyio
async def test_one_hundred_twenty_first_request_returns_429() -> None:
    async def ok(_request):
        return PlainTextResponse("ok")

    starlette_app = Starlette(routes=[Route("/v1/wallets", ok)])
    limited = RateLimitMiddleware(starlette_app, requests_per_minute=120)
    transport = ASGITransport(app=limited)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        statuses = [
            (
                await http.get("/v1/wallets", headers={"X-API-Key": "reviewer-key"})
            ).status_code
            for _ in range(121)
        ]

    assert statuses[:120] == [200] * 120
    assert statuses[120] == 429


@pytest.mark.anyio
async def test_auth_gated_401_is_still_counted() -> None:
    """Failing auth does not skip the limiter; the bucket is the key value."""

    async def deny(_request):
        return PlainTextResponse("no", status_code=401)

    starlette_app = Starlette(routes=[Route("/v1/wallets", deny)])
    limited = RateLimitMiddleware(starlette_app, requests_per_minute=2)
    transport = ASGITransport(app=limited)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        first = await http.get("/v1/wallets", headers={"X-API-Key": "reviewer-key"})
        second = await http.get("/v1/wallets", headers={"X-API-Key": "reviewer-key"})
        third = await http.get("/v1/wallets", headers={"X-API-Key": "reviewer-key"})

    assert first.status_code == 401
    assert second.status_code == 401
    assert third.status_code == 429
    assert first.headers["X-RateLimit-Limit"] == "2"


def test_root_and_discover_publish_the_same_rate_limits() -> None:
    from fastapi.testclient import TestClient as FastAPITestClient

    from app.main import app

    client = FastAPITestClient(app)
    published = client.get("/").json()["rate_limits"]
    assert published == client.get("/v1/discover").json()["rate_limits"]
    assert published == rate_limit_discovery()
