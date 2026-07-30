"""Tests for Redis→memory fallback observability and fail-closed posture."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core.config import get_settings
from app.core.health import gather_dependency_report
from app.core.rate_limiter import RateLimitMiddleware
from app.core.runtime_degradation import (
    get_runtime_degradation,
    mark_durable_state_fell_back,
    mark_rate_limiter_memory_fallback,
    reset_runtime_degradation,
)
from app.main import app


@pytest.fixture(autouse=True)
def _reset_degradation():
    reset_runtime_degradation()
    yield
    reset_runtime_degradation()


def test_runtime_degradation_flags_surface_on_health_payload():
    mark_rate_limiter_memory_fallback()
    mark_durable_state_fell_back("redis")
    snap = get_runtime_degradation()
    assert snap["degraded"] is True
    assert snap["rate_limiter"]["using_memory_fallback"] is True
    assert snap["durable_state"]["fell_back_to_memory"] is True
    assert snap["durable_state"]["intended_backend"] == "redis"


@pytest.mark.anyio
async def test_health_dependencies_reports_runtime_degradation():
    mark_rate_limiter_memory_fallback()
    report = await gather_dependency_report()
    assert "runtime_degradation" in report
    assert report["runtime_degradation"]["degraded"] is True
    assert report["status"] == "degraded"
    assert "runtime_degradation" in report["unhealthy"]


@pytest.mark.anyio
async def test_health_endpoint_includes_runtime_degradation_field(client=None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.get("/health/dependencies")
    assert resp.status_code == 200
    body = resp.json()
    assert "runtime_degradation" in body
    assert "degraded" in body["runtime_degradation"]


@pytest.mark.anyio
async def test_production_like_redis_outage_fails_closed(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "REDIS_URL", "redis://127.0.0.1:1/0")

    async def ok(_request):
        return PlainTextResponse("ok")

    starlette_app = Starlette(routes=[Route("/v1/ping", ok)])
    limited = RateLimitMiddleware(starlette_app, requests_per_minute=100)
    # Force the Redis path without relying on OS-level connection refusal
    # (CI runners can behave differently for 127.0.0.1:1).
    limited._redis_url = "redis://127.0.0.1:1/0"

    async def _redis_unavailable():
        mark_rate_limiter_memory_fallback()
        return None

    limited._get_redis = _redis_unavailable  # type: ignore[method-assign]

    async def call_next(request):
        return PlainTextResponse("ok")

    from starlette.requests import Request
    from starlette.datastructures import Headers

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/v1/ping",
        "raw_path": b"/v1/ping",
        "query_string": b"",
        "headers": Headers({"x-api-key": "prod-agent-key-1"}).raw,
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    }
    request = Request(scope)
    response = await limited.dispatch(request, call_next)
    assert response.status_code == 503
    payload = response.body
    assert b"rate_limiter_unavailable" in payload
    assert get_runtime_degradation()["rate_limiter"]["using_memory_fallback"] is True
