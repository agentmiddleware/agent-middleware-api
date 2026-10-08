"""Revoke status codes: missing versus already-settled permits.

A dashboard must tell "no such permit" (404) apart from "already revoked"
(409). Revocation is issuer-only: the caller must hold the issuer wallet
(or be a bootstrap admin).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.test_trust_helpers import (
    BOOTSTRAP_HEADERS,
    create_tool_permit,
    provision_agent_wallet,
)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_first_revoke_returns_200_with_revoked_status(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="revoke-status-tool",
    )
    resp = await client.post(
        f"/v1/permits/{permit['permit_id']}/revoke",
        headers=provisioned["agent_headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"


@pytest.mark.anyio
async def test_revoke_unknown_permit_returns_404(client, clean_database):
    await provision_agent_wallet(client)
    resp = await client.post(
        "/v1/permits/permit-does-not-exist/revoke",
        headers=BOOTSTRAP_HEADERS,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "permit_not_found"


@pytest.mark.anyio
async def test_revoke_already_revoked_permit_returns_409_not_404(
    client, clean_database
):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="revoke-twice-tool",
    )
    first = await client.post(
        f"/v1/permits/{permit['permit_id']}/revoke",
        headers=provisioned["agent_headers"],
    )
    assert first.status_code == 200

    second = await client.post(
        f"/v1/permits/{permit['permit_id']}/revoke",
        headers=provisioned["agent_headers"],
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "permit_already_revoked"


@pytest.mark.anyio
async def test_revoke_by_unrelated_wallet_is_forbidden(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    other = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="revoke-stranger-tool",
    )
    resp = await client.post(
        f"/v1/permits/{permit['permit_id']}/revoke",
        headers=other["agent_headers"],
    )
    assert resp.status_code == 403
