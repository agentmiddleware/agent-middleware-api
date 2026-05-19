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
async def test_bootstrap_admin_can_filter_paginate_and_summarize_audit_events(
    client,
    clean_database,
):
    await record_audit_event(
        event="billing.charge",
        wallet_id="wallet-1",
        tool="billing",
        endpoint="/v1/billing/charge",
        auth_source="bootstrap",
        key_id="key-1",
        request_id="req-billing-1",
        ok=True,
        metadata={"credits": "2.0"},
    )
    await record_audit_event(
        event="planner.optimize",
        wallet_id="wallet-1",
        tool="planner",
        endpoint="/v1/planner/optimize",
        auth_source="bootstrap",
        key_id="key-1",
        request_id="req-planner-1",
        ok=False,
        error="infeasible",
        metadata={"status": "Infeasible"},
    )
    await record_audit_event(
        event="sandbox.evaluate",
        wallet_id="wallet-2",
        tool="sandbox",
        endpoint="/v1/sandbox/environments/env-1/evaluate",
        auth_source="bootstrap",
        key_id="key-2",
        request_id="req-sandbox-1",
        ok=True,
    )

    response = await client.get(
        "/v1/audit/events?wallet_id=wallet-1&limit=1&offset=1&summary=true",
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["limit"] == 1
    assert data["offset"] == 1
    assert len(data["events"]) == 1
    assert data["events"][0]["wallet_id"] == "wallet-1"
    assert data["summary"] == {
        "total": 2,
        "ok": 1,
        "failed": 1,
        "by_event": {
            "billing.charge": 1,
            "planner.optimize": 1,
        },
    }


@pytest.mark.anyio
async def test_db_wallet_key_can_list_own_wallet_audit_events(client, clean_database):
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
    key_id = key_response.json()["key_id"]

    await record_audit_event(
        event="billing.charge",
        wallet_id=wallet_id,
        tool="billing",
        endpoint="/v1/billing/charge",
        auth_source="db",
        key_id=key_id,
        request_id="req-own-wallet-audit",
        ok=True,
    )
    await record_audit_event(
        event="mcp.invoke",
        wallet_id=wallet_id,
        tool="echo",
        endpoint="/mcp/messages",
        auth_source="bootstrap",
        key_id=None,
        request_id="req-own-wallet-admin-audit",
        ok=True,
    )
    await record_audit_event(
        event="billing.charge",
        wallet_id="wallet-other",
        tool="billing",
        endpoint="/v1/billing/charge",
        auth_source="db",
        key_id="key-other",
        request_id="req-other-wallet-audit",
        ok=True,
    )

    response = await client.get(
        f"/v1/audit/events?wallet_id={wallet_id}",
        headers={"X-API-Key": wallet_api_key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert {event["wallet_id"] for event in data["events"]} == {wallet_id}
    assert {event["request_id"] for event in data["events"]} == {
        "req-own-wallet-audit",
        "req-own-wallet-admin-audit",
    }


@pytest.mark.anyio
async def test_db_wallet_key_cannot_list_global_audit_events(client, clean_database):
    sponsor_response = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Audit Route Test Corp",
            "email": "audit-route-global@test.com",
        },
        headers={"X-API-Key": "test-key"},
    )
    assert sponsor_response.status_code == 201
    wallet_id = sponsor_response.json()["wallet_id"]

    key_response = await client.post(
        "/v1/api-keys",
        json={
            "wallet_id": wallet_id,
            "key_name": "audit-route-global-test-key",
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


@pytest.mark.anyio
async def test_db_wallet_key_cannot_list_other_wallet_audit_events(
    client,
    clean_database,
):
    sponsor_response = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Audit Route Test Corp",
            "email": "audit-route-cross-wallet@test.com",
        },
        headers={"X-API-Key": "test-key"},
    )
    assert sponsor_response.status_code == 201
    wallet_id = sponsor_response.json()["wallet_id"]

    key_response = await client.post(
        "/v1/api-keys",
        json={
            "wallet_id": wallet_id,
            "key_name": "audit-route-cross-wallet-test-key",
        },
        headers={"X-API-Key": "test-key"},
    )
    assert key_response.status_code == 201
    wallet_api_key = key_response.json()["api_key"]

    response = await client.get(
        "/v1/audit/events?wallet_id=wallet-other",
        headers={"X-API-Key": wallet_api_key},
    )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_db_wallet_key_cannot_request_audit_summary(client, clean_database):
    sponsor_response = await client.post(
        "/v1/billing/wallets/sponsor",
        json={
            "sponsor_name": "Audit Route Test Corp",
            "email": "audit-route-summary@test.com",
        },
        headers={"X-API-Key": "test-key"},
    )
    assert sponsor_response.status_code == 201
    wallet_id = sponsor_response.json()["wallet_id"]

    key_response = await client.post(
        "/v1/api-keys",
        json={
            "wallet_id": wallet_id,
            "key_name": "audit-route-summary-test-key",
        },
        headers={"X-API-Key": "test-key"},
    )
    assert key_response.status_code == 201
    wallet_api_key = key_response.json()["api_key"]

    response = await client.get(
        f"/v1/audit/events?wallet_id={wallet_id}&summary=true",
        headers={"X-API-Key": wallet_api_key},
    )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_audit_summary_requires_bootstrap_admin(client, clean_database):
    response = await client.get("/v1/audit/events?summary=true")

    assert response.status_code in (401, 403)
