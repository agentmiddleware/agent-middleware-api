"""CORS must never reflect an arbitrary Origin with credentials enabled.

Regression guard for the wildcard + ``allow_credentials`` misconfiguration:
with ``CORS_ORIGINS="*"`` (the default) and ``allow_credentials=True``,
Starlette echoes the caller's ``Origin`` back and still returns
``Access-Control-Allow-Credentials: true`` — which lets any website make
credentialed cross-origin reads against the trust plane. The app disables
credentials whenever the origin list is a wildcard, so the dangerous
combination can never be served.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

EVIL_ORIGIN = "https://evil.example"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_wildcard_cors_does_not_reflect_origin_with_credentials(client):
    resp = await client.get("/llm.txt", headers={"Origin": EVIL_ORIGIN})
    acao = resp.headers.get("access-control-allow-origin")
    acac = resp.headers.get("access-control-allow-credentials")

    # The dangerous combination is a reflected caller Origin together with
    # credentials. Under the wildcard default the origin must never be echoed
    # back as the caller's, and credentials must not be allowed.
    assert acao != EVIL_ORIGIN
    assert acac != "true"


@pytest.mark.anyio
async def test_wildcard_cors_preflight_is_not_credentialed(client):
    resp = await client.options(
        "/v1/permits",
        headers={
            "Origin": EVIL_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") != EVIL_ORIGIN
    assert resp.headers.get("access-control-allow-credentials") != "true"
