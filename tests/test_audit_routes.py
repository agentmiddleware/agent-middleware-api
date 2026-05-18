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
    response = await client.get(
        "/v1/audit/events",
        headers={"X-API-Key": "not-a-real-db-key"},
    )

    assert response.status_code in {403, 503}
