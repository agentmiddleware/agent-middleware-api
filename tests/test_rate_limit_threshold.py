"""Documented rate-limit threshold: 120/min, 429 on the 121st request.

A 40-request burst drawing zero 429s is the intended posture, not a missing
limiter. Auth-gated paths are counted. Discovery/docs/health are exempt.
"""

from __future__ import annotations

import time

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core.rate_limiter import (
    _MEMORY_BUCKET_SWEEP_THRESHOLD,
    RateLimitMiddleware,
    rate_limit_discovery,
)


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


@pytest.mark.anyio
async def test_rotating_invalid_keys_share_one_bounded_budget() -> None:
    """A fresh invalid X-API-Key per request must not mint a fresh budget.

    The per-key bucket is chosen from a caller-supplied header before the key
    is verified, so rejected credentials are charged to one shared per-client
    bucket at ten times the per-key limit. Every request below carries a
    distinct key value and would otherwise get its own budget forever.
    """

    async def deny(_request):
        return PlainTextResponse("no", status_code=401)

    starlette_app = Starlette(routes=[Route("/v1/wallets", deny)])
    limited = RateLimitMiddleware(starlette_app, requests_per_minute=2)
    ceiling = limited.preauth_limit
    assert ceiling == 20

    transport = ASGITransport(app=limited)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        statuses = [
            (
                await http.get(
                    "/v1/wallets",
                    headers={"X-API-Key": f"invalid-key-{index}"},
                )
            ).status_code
            for index in range(ceiling + 1)
        ]

    assert statuses[:ceiling] == [401] * ceiling
    assert statuses[ceiling] == 429


@pytest.mark.anyio
async def test_accepted_credentials_never_touch_the_shared_bucket() -> None:
    """The shared bucket bounds rejected credentials only, not real traffic."""

    async def ok(_request):
        return PlainTextResponse("ok")

    starlette_app = Starlette(routes=[Route("/v1/wallets", ok)])
    limited = RateLimitMiddleware(starlette_app, requests_per_minute=2)

    transport = ASGITransport(app=limited)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        statuses = [
            (
                await http.get(
                    "/v1/wallets",
                    headers={"X-API-Key": f"accepted-key-{index}"},
                )
            ).status_code
            for index in range(limited.preauth_limit + 5)
        ]

    assert statuses == [200] * len(statuses)


@pytest.mark.anyio
async def test_shared_bucket_reads_are_not_charged() -> None:
    """Asking whether the bucket is spent must not spend from it."""

    async def ok(_request):
        return PlainTextResponse("ok")

    starlette_app = Starlette(routes=[Route("/v1/wallets", ok)])
    limited = RateLimitMiddleware(starlette_app, requests_per_minute=2)
    bucket = "probe-bucket"
    now = time.time()

    for _ in range(limited.preauth_limit + 1):
        exhausted, _reset = await limited._peek_limit(bucket, now, 1)
        assert exhausted is False
    assert bucket not in limited._requests

    await limited._charge(bucket, now, limited.preauth_limit)
    exhausted, reset_in = await limited._peek_limit(bucket, now, 1)
    assert exhausted is True
    assert reset_in >= 1


@pytest.mark.anyio
async def test_expired_in_memory_buckets_are_swept() -> None:
    """Rotating key values must not leave a list behind per value forever."""

    async def ok(_request):
        return PlainTextResponse("ok")

    limited = RateLimitMiddleware(Starlette(routes=[Route("/v1/w", ok)]))
    stale = time.time() - 3600
    for index in range(_MEMORY_BUCKET_SWEEP_THRESHOLD + 1):
        limited._requests[f"rotated-key-{index}"] = [stale]

    await limited._check_limit_in_memory("live-key", time.time())

    assert list(limited._requests) == ["live-key"]


def test_published_window_does_not_claim_one_backend_s_algorithm() -> None:
    """Redis counts a fixed window; the in-memory fallback counts a rolling one."""

    payload = rate_limit_discovery()
    assert payload["window_seconds"] == 60
    assert payload["window_accounting"] == (
        "fixed_window_shared_rolling_window_in_memory"
    )
    assert payload["rejected_credentials_scope"] == "shared_per_client_bucket"
