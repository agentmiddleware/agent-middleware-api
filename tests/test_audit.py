"""
Tests for structured audit events and the admin-only audit export endpoint.
"""

import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from app.audit.lightweight import get_recent_audit, record_audit
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def test_recent_audit_buffer_records_and_filters():
    marker = f"test.audit.{uuid.uuid4().hex[:8]}"
    record_audit(marker, detail="hello")
    events = get_recent_audit(limit=1000, event_prefix=marker)
    assert len(events) == 1
    assert events[0]["event"] == marker
    assert events[0]["detail"] == "hello"
    assert "ts" in events[0]


@pytest.mark.anyio
async def test_audit_export_requires_admin(client):
    # A wallet-scoped DB key is not a bootstrap admin.
    headers = {"X-API-Key": "test-key"}
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": f"a-{uuid.uuid4().hex[:6]}", "email": "a@test.example"},
        headers=headers,
    )
    wallet_id = sponsor.json()["wallet_id"]
    key_resp = await client.post(
        "/v1/api-keys",
        json={"wallet_id": wallet_id, "key_name": "scoped"},
        headers=headers,
    )
    scoped = {"X-API-Key": key_resp.json()["api_key"]}

    denied = await client.get("/v1/admin/audit", headers=scoped)
    assert denied.status_code == 403

    allowed = await client.get("/v1/admin/audit", headers=headers)
    assert allowed.status_code == 200
    assert "events" in allowed.json()


@pytest.mark.anyio
async def test_wallet_access_denial_is_audited(client):
    headers = {"X-API-Key": "test-key"}
    sponsor = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": f"b-{uuid.uuid4().hex[:6]}", "email": "b@test.example"},
        headers=headers,
    )
    wallet_id = sponsor.json()["wallet_id"]
    key_resp = await client.post(
        "/v1/api-keys",
        json={"wallet_id": wallet_id, "key_name": "scoped"},
        headers=headers,
    )
    scoped = {"X-API-Key": key_resp.json()["api_key"]}

    # Scoped key tries to act for a different wallet -> denied + audited.
    denied = await client.post(
        "/v1/permits/issue",
        json={"wallet_id": "someone-elses-wallet", "scope": ["*"]},
        headers=scoped,
    )
    assert denied.status_code == 403

    export = await client.get(
        "/v1/admin/audit?event=auth.wallet_access_denied", headers=headers
    )
    assert export.status_code == 200
    events = export.json()["events"]
    assert any(e.get("target_wallet") == "someone-elses-wallet" for e in events)
