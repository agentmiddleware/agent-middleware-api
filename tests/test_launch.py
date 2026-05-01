"""
Tests for Day 1 Launch Sequence.
Validates the full production bootstrap:
  FUND → INFILTRATE → IGNITE → ARM

This is the integration test that proves the entire B2A startup
can boot from zero to LIVE in a single API call.
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
# Full Launch Sequence (The Big Red Button)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_full_launch_sequence(client):
    """Test the complete Day 1 launch — fund, infiltrate, ignite, arm."""
    resp = await client.post(
        "/v1/launch",
        json={
            "sponsor_name": "Test Founder",
            "sponsor_email": "test@b2a.com",
            "seed_capital_usd": 50.0,
            "agent_ids": ["agent-alpha", "agent-beta"],
            "agent_budget_credits": 5000.0,
            "platforms": ["youtube_shorts", "tiktok"],
            "max_posts_per_day": 3,
        },
        headers=HEADERS,
    )
    assert resp.status_code == 201, f"Launch failed: {resp.text}"
    data = resp.json()

    # Status
    assert data["status"] == "LIVE"

    # Fund phase
    assert data["sponsor_wallet_id"].startswith("spn-")
    assert len(data["agent_wallet_ids"]) == 2
    assert all(wid.startswith("agt-") for wid in data["agent_wallet_ids"])
    assert data["total_credits_seeded"] == 50000.0  # $50 × 1000 credits/$

    # Infiltrate phase
    assert data["apis_crawled"] == 6  # 6 simulated APIs
    assert data["directories_registered"] == 4
    assert data["visibility_score"] > 0

    # Ignite phase
    assert data["campaign_id"]
    assert data["total_content_pieces"] > 20  # 3 hooks × multiple formats
    assert data["scheduled_posts"] > 0
    assert data["estimated_total_views"] > 0

    # Arm phase
    assert data["security_score"] > 0
    assert data["attack_vectors_tested"] > 0

    # Summary dict
    assert "fund" in data["summary"]
    assert "infiltrate" in data["summary"]
    assert "ignite" in data["summary"]
    assert "arm" in data["summary"]


@pytest.mark.anyio
async def test_launch_creates_wallets_with_correct_balances(client):
    """Verify wallet math: $50 seed → 50K credits, minus agent provisions."""
    resp = await client.post(
        "/v1/launch",
        json={
            "sponsor_name": "Math Test Sponsor",
            "sponsor_email": "math@test.com",
            "seed_capital_usd": 100.0,
            "agent_ids": ["calc-agent-1"],
            "agent_budget_credits": 20000.0,
        },
        headers=HEADERS,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["total_credits_seeded"] == 100000.0  # $100 × 1000


@pytest.mark.anyio
async def test_launch_content_pieces_scale_with_hooks(client):
    """Three hooks should produce significantly more content than a single-hook campaign."""
    resp = await client.post(
        "/v1/launch",
        json={
            "sponsor_name": "Content Scale Test",
            "sponsor_email": "scale@test.com",
            "seed_capital_usd": 10.0,
            "agent_ids": ["scaler"],
            "agent_budget_credits": 5000.0,
            "platforms": ["tiktok"],
        },
        headers=HEADERS,
    )
    assert resp.status_code == 201
    data = resp.json()
    # 3 default hooks with 5-6 formats each, multiplied by hook format multipliers
    # Should produce 40+ pieces total
    assert data["total_content_pieces"] >= 30


@pytest.mark.anyio
async def test_launch_security_score_exists(client):
    """Red Team scan should produce a non-zero security score."""
    resp = await client.post(
        "/v1/launch",
        json={
            "sponsor_name": "Security Test",
            "sponsor_email": "sec@test.com",
            "seed_capital_usd": 10.0,
            "agent_ids": ["sentinel"],
            "agent_budget_credits": 5000.0,
        },
        headers=HEADERS,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert 0 < data["security_score"] <= 100


@pytest.mark.anyio
async def test_launch_visibility_score_grows_with_registrations(client):
    """4 directory registrations + 6 crawled APIs should yield meaningful visibility."""
    resp = await client.post(
        "/v1/launch",
        json={
            "sponsor_name": "Visibility Test",
            "sponsor_email": "vis@test.com",
            "seed_capital_usd": 10.0,
            "agent_ids": ["vis-agent"],
            "agent_budget_credits": 5000.0,
        },
        headers=HEADERS,
    )
    assert resp.status_code == 201
    data = resp.json()
    # 4 registrations × 10pts + 6 APIs × 5pts = 40 + 30 = 70
    assert data["visibility_score"] >= 50


@pytest.mark.anyio
async def test_launch_reports_endpoint(client):
    """After launching, reports should be retrievable."""
    # First launch
    await client.post(
        "/v1/launch",
        json={"sponsor_name": "Report Test", "sponsor_email": "r@t.com",
              "seed_capital_usd": 10.0, "agent_ids": ["reporter"],
              "agent_budget_credits": 5000.0},
        headers=HEADERS,
    )

    resp = await client.get("/v1/launch/reports", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert len(data["reports"]) >= 1


@pytest.mark.anyio
async def test_launch_requires_api_key(client):
    """Launch must require authentication."""
    resp = await client.post("/v1/launch", json={})
    assert resp.status_code in (401, 403)


@pytest.mark.anyio
async def test_launch_with_minimal_config(client):
    """Launch with all defaults should still succeed."""
    resp = await client.post(
        "/v1/launch",
        json={},  # All defaults
        headers=HEADERS,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "LIVE"
    assert data["total_content_pieces"] > 0


@pytest.mark.anyio
async def test_launch_summary_has_all_phases(client):
    """Summary dict should contain all four phase receipts."""
    resp = await client.post(
        "/v1/launch",
        json={"sponsor_name": "Summary Test", "sponsor_email": "s@t.com",
              "seed_capital_usd": 10.0, "agent_ids": ["sum-agent"],
              "agent_budget_credits": 5000.0},
        headers=HEADERS,
    )
    assert resp.status_code == 201
    summary = resp.json()["summary"]

    assert "fund" in summary
    assert "infiltrate" in summary
    assert "ignite" in summary
    assert "arm" in summary

    # Fund
    assert "sponsor_wallet" in summary["fund"]
    assert "credits_seeded" in summary["fund"]

    # Infiltrate
    assert "apis_indexed" in summary["infiltrate"]
    assert "visibility" in summary["infiltrate"]

    # Ignite
    assert "content_pieces" in summary["ignite"]
    assert "platforms" in summary["ignite"]

    # Arm
    assert "security_score" in summary["arm"]
    assert "vectors_tested" in summary["arm"]
