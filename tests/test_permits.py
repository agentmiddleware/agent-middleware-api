from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_signed_permit_verifies_for_wallet_tool_and_budget(
    client,
    clean_database,
):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="trust-echo",
    )

    verify_resp = await client.post(
        "/v1/permits/verify",
        json={
            "permit_id": permit["permit_id"],
            "wallet_id": provisioned["agent_wallet_id"],
            "tool": "trust-echo",
            "estimated_credits": 2,
        },
        headers=provisioned["agent_headers"],
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["valid"] is True


@pytest.mark.anyio
async def test_permit_rejects_out_of_scope_tool(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="allowed-tool",
    )

    verify_resp = await client.post(
        "/v1/permits/verify",
        json={
            "permit_id": permit["permit_id"],
            "wallet_id": provisioned["agent_wallet_id"],
            "tool": "blocked-tool",
            "estimated_credits": 2,
        },
        headers=provisioned["agent_headers"],
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["valid"] is False
    assert verify_resp.json()["reason"] == "permit_tool_not_allowed"
