"""Coverage for request ID assignment and propagation.

Routers attach ``X-Request-ID`` to audit and billing-governance records, but
before ``RequestIdMiddleware`` nothing assigned one and nothing bounded the
inbound value: responses never carried it back, and an overlong caller value
flowed straight toward an audit column capped at 100 characters. These tests
prove the boundary now assigns, bounds, and echoes exactly one safe value on
every path, including short-circuit responses the route never sees.
"""

from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.main import add_cors_middleware
from app.main import app as real_app
from app.middleware.request_body_limit import RequestBodyLimitMiddleware
from app.middleware.request_id import RequestIdMiddleware, normalize_request_id

SAFE = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")


async def _observe(request: Request):
    """Report every channel the middleware promises to normalize."""
    return JSONResponse(
        {
            "header": request.headers.get("x-request-id"),
            "header_count": len(request.headers.getlist("x-request-id")),
            "state": request.state.request_id,
        }
    )


def _app() -> Starlette:
    application = Starlette(routes=[Route("/observe", _observe, methods=["GET"])])
    application.add_middleware(RequestIdMiddleware)
    return application


def _client(application) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://test")


@pytest.mark.anyio
async def test_valid_caller_id_is_kept_and_echoed():
    async with _client(_app()) as client:
        r = await client.get("/observe", headers={"X-Request-ID": "req-abc_123.X"})
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "header": "req-abc_123.X",
        "header_count": 1,
        "state": "req-abc_123.X",
    }
    assert r.headers["x-request-id"] == "req-abc_123.X"


@pytest.mark.anyio
async def test_missing_id_is_generated_and_echoed():
    async with _client(_app()) as client:
        r = await client.get("/observe")
    body = r.json()
    assert body["header"] is not None
    assert body["header"] == body["state"] == r.headers["x-request-id"]
    assert SAFE.match(body["header"]), body["header"]


@pytest.mark.anyio
async def test_overlong_id_is_replaced_not_forwarded():
    """A 200-character value must never reach the audit column downstream."""
    evil = "r" * 200
    async with _client(_app()) as client:
        r = await client.get("/observe", headers={"X-Request-ID": evil})
    body = r.json()
    assert body["header"] != evil
    assert body["header"] == body["state"] == r.headers["x-request-id"]
    assert len(body["header"]) <= 128
    assert SAFE.match(body["header"]), body["header"]


@pytest.mark.anyio
@pytest.mark.parametrize("evil", ["has space", "tab\there", "semi;colon", ""])
async def test_unsafe_characters_are_replaced(evil: str):
    async with _client(_app()) as client:
        r = await client.get("/observe", headers={"X-Request-ID": evil})
    body = r.json()
    assert body["header"] != evil or evil == ""
    assert SAFE.match(body["header"]), repr(body["header"])
    assert body["header"] == r.headers["x-request-id"]


@pytest.mark.anyio
async def test_competing_values_collapse_to_one():
    async with _client(_app()) as client:
        r = await client.get(
            "/observe",
            headers=[("X-Request-ID", "first-good"), ("X-Request-ID", "second-good")],
        )
    body = r.json()
    assert body["header"] == "first-good"
    assert body["header_count"] == 1
    assert r.headers["x-request-id"] == "first-good"


@pytest.mark.anyio
async def test_short_circuit_413_carries_a_generated_id():
    """The 413 never reaches the route; the ID must still be assigned."""
    application = Starlette(routes=[Route("/observe", _observe, methods=["POST"])])
    application.add_middleware(RequestBodyLimitMiddleware, max_body_size=16)
    application.add_middleware(RequestIdMiddleware)
    async with _client(application) as client:
        r = await client.post("/observe", content=b"x" * 17)
    assert r.status_code == 413
    assert SAFE.match(r.headers["x-request-id"]), r.headers["x-request-id"]


@pytest.mark.anyio
async def test_cors_preflight_is_stamped_and_exposes_the_id():
    """Credentialed browser callers must be able to read the echoed ID."""
    application = Starlette(routes=[Route("/observe", _observe, methods=["GET"])])
    add_cors_middleware(application, ["https://good.example"])
    application.add_middleware(RequestIdMiddleware)
    # Registration order mirrors app/main.py (CORS, then RequestIdMiddleware,
    # so the ID layer wraps outside CORS) and the preflight short-circuit
    # passes back through it.
    async with _client(application) as client:
        preflight = await client.options(
            "/observe",
            headers={
                "Origin": "https://good.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        simple = await client.get(
            "/observe", headers={"Origin": "https://good.example"}
        )
    assert SAFE.match(preflight.headers["x-request-id"])
    assert "x-request-id" in simple.headers["access-control-expose-headers"].lower()


@pytest.mark.anyio
async def test_non_http_scopes_pass_through():
    seen = []

    async def spy(scope, receive, send):
        seen.append(scope["type"])

    async def noop():
        return {}

    async def send(message):
        pass

    await RequestIdMiddleware(spy)({"type": "websocket"}, noop, send)
    assert seen == ["websocket"]


def test_normalize_request_id_unit_cases():
    assert normalize_request_id(["keep-me"]) == "keep-me"
    assert normalize_request_id([]) != ""
    assert normalize_request_id(["bad value", "good-one"]) == "good-one"
    generated = normalize_request_id(["x" * 129])
    assert SAFE.match(generated), generated


def test_the_real_app_registers_request_id_outermost():
    """The propagation is wired into the shipped app, not just available."""
    matches = [
        middleware
        for middleware in real_app.user_middleware
        if middleware.cls is RequestIdMiddleware
    ]
    assert len(matches) == 1
    # Starlette's add_middleware prepends, so index 0 wraps furthest out.
    assert real_app.user_middleware[0].cls is RequestIdMiddleware
