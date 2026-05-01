"""
Golden-path smoke test for the production-beta product loop.

This mirrors docs/golden-path.md: bootstrap provisioning, wallet-scoped runtime
key, ownership denial, dry-run cost estimation, discovery, and inspection.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_wallet_scoped_agent_golden_path(client, clean_database):
    bootstrap_headers = {"X-API-Key": "test-key"}

    # Agent-facing discovery surfaces should be reachable.
    for path in ("/.well-known/agent.json", "/llm.txt", "/mcp/tools.json"):
        resp = await client.get(path, headers=bootstrap_headers)
        assert resp.status_code == 200

    sponsor_resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Golden Path Sponsor",
            "email": "golden@example.com",
            "initial_credits": 10000,
            "require_kyc": False,
        },
        headers=bootstrap_headers,
    )
    assert sponsor_resp.status_code == 201
    sponsor_wallet_id = sponsor_resp.json()["wallet_id"]

    agent_resp = await client.post(
        "/v1/billing/wallets/agent",
        json={
            "sponsor_wallet_id": sponsor_wallet_id,
            "agent_id": "golden-agent-001",
            "budget_credits": 1000,
            "daily_limit": 250,
        },
        headers=bootstrap_headers,
    )
    assert agent_resp.status_code == 201
    agent_wallet_id = agent_resp.json()["wallet_id"]

    key_resp = await client.post(
        "/v1/api-keys",
        json={
            "wallet_id": agent_wallet_id,
            "key_name": "golden-agent-runtime",
            "expires_in_days": 30,
        },
        headers=bootstrap_headers,
    )
    assert key_resp.status_code == 201
    agent_api_key = key_resp.json()["api_key"]
    agent_headers = {"X-API-Key": agent_api_key}

    own_wallet_resp = await client.get(
        f"/v1/billing/wallets/{agent_wallet_id}",
        headers=agent_headers,
    )
    assert own_wallet_resp.status_code == 200
    assert own_wallet_resp.json()["wallet_id"] == agent_wallet_id

    sponsor_read_resp = await client.get(
        f"/v1/billing/wallets/{sponsor_wallet_id}",
        headers=agent_headers,
    )
    assert sponsor_read_resp.status_code == 403

    dry_run_resp = await client.post(
        "/v1/billing/dry-run/session",
        json={"wallet_id": agent_wallet_id},
        headers=agent_headers,
    )
    assert dry_run_resp.status_code == 201
    dry_run_session_id = dry_run_resp.json()["session_id"]

    simulate_resp = await client.post(
        "/v1/billing/dry-run/charge",
        json={
            "wallet_id": agent_wallet_id,
            "service": "telemetry_pm",
            "units": 1,
            "description": "Estimate anomaly review cost",
            "dry_run_session_id": dry_run_session_id,
        },
        headers=agent_headers,
    )
    assert simulate_resp.status_code == 200
    simulation = simulate_resp.json()
    assert simulation["dry_run"] is True
    assert simulation["wallet_id"] == agent_wallet_id
    assert simulation["would_succeed"] is True

    mcp_resp = await client.get("/mcp/tools.json", headers=agent_headers)
    assert mcp_resp.status_code == 200
    assert "tools" in mcp_resp.json()

    ledger_resp = await client.get(
        f"/v1/billing/ledger/{agent_wallet_id}",
        headers=agent_headers,
    )
    assert ledger_resp.status_code == 200
    assert ledger_resp.json()["wallet_id"] == agent_wallet_id

    velocity_resp = await client.get(
        f"/v1/billing/wallets/{agent_wallet_id}/velocity",
        headers=agent_headers,
    )
    assert velocity_resp.status_code == 200
