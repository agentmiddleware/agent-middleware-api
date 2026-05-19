from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.trust import PermitCreateRequest
from app.services.idempotency import get_idempotency_service
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


@pytest.mark.anyio
async def test_permit_create_rejects_in_progress_idempotency_key(
    client,
    clean_database,
):
    provisioned = await provision_agent_wallet(client)
    request_payload = {
        "issuer_wallet_id": provisioned["agent_wallet_id"],
        "subject_wallet_id": provisioned["agent_wallet_id"],
        "subject_key_id": provisioned["key_id"],
        "allowed_tools": ["in-progress-permit-tool"],
        "scopes": ["tool:in-progress-permit-tool:invoke", "billing:charge"],
        "max_credits": 50,
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(minutes=30)
        ).isoformat(),
    }
    await get_idempotency_service().begin(
        wallet_id=provisioned["agent_wallet_id"],
        endpoint="/v1/permits",
        idempotency_key="permit-in-progress-key",
        request_payload=PermitCreateRequest(**request_payload).model_dump(mode="json"),
    )

    resp = await client.post(
        "/v1/permits",
        json=request_payload,
        headers={"X-API-Key": "test-key", "Idempotency-Key": "permit-in-progress-key"},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "idempotency_in_progress"
