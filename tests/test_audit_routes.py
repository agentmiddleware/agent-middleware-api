import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.audit_log import record_audit_event


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_bootstrap_admin_can_list_audit_events(client, clean_database):
    await record_audit_event(
        event="mcp.invoke",
        wallet_id="wallet-1",
        tool="echo",
        endpoint="/mcp/messages",
        auth_source="db",
        key_id="key-1",
        policy_decision_id="pol-1",
        request_id="req-1",
        ok=True,
        metadata={"cost": 2.0},
    )

    response = await client.get(
        "/v1/audit/events?wallet_id=wallet-1",
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["events"][0]["wallet_id"] == "wallet-1"
    assert data["events"][0]["metadata"]["cost"] == 2.0


@pytest.mark.anyio
async def test_db_wallet_key_cannot_list_audit_events(client, clean_database):
    sponsor_response = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Audit Route Test Corp",
            "email": "audit-route@test.com",
        },
        headers={"X-API-Key": "test-key"},
    )
    assert sponsor_response.status_code == 201
    wallet_id = sponsor_response.json()["wallet_id"]

    key_response = await client.post(
        "/v1/api-keys",
        json={
            "wallet_id": wallet_id,
            "key_name": "audit-route-test-key",
        },
        headers={"X-API-Key": "test-key"},
    )
    assert key_response.status_code == 201
    wallet_api_key = key_response.json()["api_key"]

    response = await client.get(
        "/v1/audit/events",
        headers={"X-API-Key": wallet_api_key},
    )

    assert response.status_code == 403
