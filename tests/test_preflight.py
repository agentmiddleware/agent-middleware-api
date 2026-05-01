"""
Tests for the Pre-Flight Readiness Check endpoint.
Validates that preflight catches placeholder values, missing keys,
and bad domains before the founder hits the big red button.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


HEADERS = {"X-API-Key": "test-key"}


# ---------------------------------------------------------------------------
# Basic Preflight
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_preflight_returns_report(client):
    """Preflight should return a structured readiness report."""
    resp = await client.post("/v1/launch/preflight", json={}, headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()

    assert "verdict" in data
    assert data["verdict"] in ("GO", "NO-GO")
    assert "total_checks" in data
    assert "passed" in data
    assert "failed" in data
    assert "checks" in data
    assert "summary" in data
    assert isinstance(data["checks"], list)
    assert len(data["checks"]) > 0


@pytest.mark.anyio
async def test_preflight_default_is_no_go(client):
    """With default placeholder config, preflight should be NO-GO."""
    resp = await client.post("/v1/launch/preflight", json={}, headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()

    # Default config has yourdomain.com and no real Stripe keys
    assert data["verdict"] == "NO-GO"
    assert data["critical_failures"] > 0


@pytest.mark.anyio
async def test_preflight_detects_placeholder_base_url(client):
    """Preflight should flag yourdomain.com as a placeholder."""
    resp = await client.post(
        "/v1/launch/preflight",
        json={"base_url": "https://api.yourdomain.com"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()

    base_url_checks = [c for c in data["checks"] if c["name"] == "base_url_valid"]
    assert len(base_url_checks) == 1
    assert base_url_checks[0]["passed"] is False
    assert base_url_checks[0]["severity"] == "critical"


@pytest.mark.anyio
async def test_preflight_accepts_real_base_url(client):
    """A real domain should pass the base_url check."""
    resp = await client.post(
        "/v1/launch/preflight",
        json={"base_url": "https://api.myrealdomain.com"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()

    base_url_checks = [c for c in data["checks"] if c["name"] == "base_url_valid"]
    assert len(base_url_checks) == 1
    assert base_url_checks[0]["passed"] is True


@pytest.mark.anyio
async def test_preflight_flags_http_base_url(client):
    """Non-HTTPS BASE_URL should trigger a warning."""
    resp = await client.post(
        "/v1/launch/preflight",
        json={"base_url": "http://api.myrealdomain.com"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()

    https_checks = [c for c in data["checks"] if c["name"] == "base_url_https"]
    assert len(https_checks) == 1
    assert https_checks[0]["passed"] is False


@pytest.mark.anyio
async def test_preflight_validates_stripe_test_key(client):
    """A Stripe test key should trigger a warning."""
    resp = await client.post(
        "/v1/launch/preflight",
        json={"stripe_secret_key": "sk_test_abc123xyz"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()

    stripe_checks = [c for c in data["checks"] if "stripe" in c["name"]]
    assert len(stripe_checks) > 0
    # sk_test_ should not pass as live
    non_live = [c for c in stripe_checks if not c["passed"]]
    assert len(non_live) > 0


@pytest.mark.anyio
async def test_preflight_accepts_stripe_live_key(client):
    """A live Stripe key should pass validation."""
    resp = await client.post(
        "/v1/launch/preflight",
        json={"stripe_secret_key": "sk_live_abc123xyz456"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()

    stripe_checks = [c for c in data["checks"] if c["name"] == "stripe_key_live"]
    assert len(stripe_checks) == 1
    assert stripe_checks[0]["passed"] is True


@pytest.mark.anyio
async def test_preflight_checks_oracle_directories(client):
    """Preflight should validate all 4 default oracle directory targets."""
    resp = await client.post("/v1/launch/preflight", json={}, headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()

    oracle_checks = [c for c in data["checks"] if c["name"].startswith("oracle_directory_")]
    assert len(oracle_checks) == 4  # 4 default directories


@pytest.mark.anyio
async def test_preflight_checks_content_source_url(client):
    """Default content source URL (yourdomain.com) should fail."""
    resp = await client.post("/v1/launch/preflight", json={}, headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()

    content_checks = [c for c in data["checks"] if c["name"] == "content_source_url"]
    assert len(content_checks) == 1
    assert content_checks[0]["passed"] is False
    assert content_checks[0]["severity"] == "critical"


@pytest.mark.anyio
async def test_preflight_check_structure(client):
    """Each check should have the required fields."""
    resp = await client.post("/v1/launch/preflight", json={}, headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()

    for check in data["checks"]:
        assert "name" in check
        assert "passed" in check
        assert "severity" in check
        assert check["severity"] in ("critical", "warning", "info")
        assert "message" in check


@pytest.mark.anyio
async def test_preflight_requires_api_key(client):
    """Preflight must require authentication."""
    resp = await client.post("/v1/launch/preflight", json={})
    assert resp.status_code in (401, 403)


@pytest.mark.anyio
async def test_preflight_summary_describes_verdict(client):
    """Summary should reference the verdict reason."""
    resp = await client.post("/v1/launch/preflight", json={}, headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["summary"]) > 10
    if data["verdict"] == "NO-GO":
        assert "NO-GO" in data["summary"] or "critical" in data["summary"].lower()


@pytest.mark.anyio
async def test_preflight_math_consistency(client):
    """passed + failed should equal total_checks."""
    resp = await client.post("/v1/launch/preflight", json={}, headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()

    assert data["passed"] + data["failed"] == data["total_checks"]
    assert data["total_checks"] == len(data["checks"])
