from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.database import get_session_factory
from app.db.models import SigningKeyModel
from app.main import app
from app.services.audit_log import record_audit_event
from app.services.receipts import get_receipt_service
from app.services.signing_keys import get_signing_key_service
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
async def test_active_signing_key_metadata_endpoint_excludes_private_key(
    client,
    clean_database,
):
    resp = await client.get("/v1/signing-keys/active", headers=BOOTSTRAP_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["key_id"]
    assert body["alg"] == "Ed25519"
    assert body["public_key_b64"]
    assert body["status"] == "active"
    assert "private_key" not in body
    assert "private_key_b64" not in body


@pytest.mark.anyio
async def test_retired_signing_key_metadata_still_verifies_payload(clean_database):
    service = get_signing_key_service()
    signature, key_id, payload_hash = await service.sign_payload(
        {"purpose": "retire-test"}
    )
    await service.retire_key_metadata(key_id)

    payload = {
        "purpose": "retire-test",
        "alg": "Ed25519",
        "kid": key_id,
        "payload_hash": payload_hash,
    }

    assert await service.verify_payload(payload, signature=signature, key_id=key_id)

    factory = get_session_factory()
    async with factory() as session:
        key = await session.get(SigningKeyModel, key_id)
        assert key is not None
        assert key.status == "retired"
        assert key.retired_at is not None


@pytest.mark.anyio
async def test_rotated_metadata_preserves_historical_trust_artifact_verification(
    client,
    clean_database,
):
    service = get_signing_key_service()
    original_key_id = service._settings.TRUST_SIGNING_KEY_ID
    await service.rotate_active_key_metadata(original_key_id)

    provisioned = await provision_agent_wallet(client)
    old_permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="historical-tool",
        idem_key="permit-before-signing-key-rotation",
    )
    old_receipt = await get_receipt_service().create_receipt(
        permit_id=old_permit["permit_id"],
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool="historical-tool",
        request_payload={"message": "before"},
        response_payload={"message": "after"},
        ledger_entry_id=None,
        credits_authorized=Decimal("2"),
        credits_charged=Decimal("0"),
        outcome="success",
        audit_event_id=None,
    )
    audit_event = await record_audit_event(
        event="trust.rotation.before",
        wallet_id=provisioned["agent_wallet_id"],
        tool="historical-tool",
        key_id=provisioned["key_id"],
        metadata={"phase": "before"},
    )

    rotated_key_id = "test-rotated-ed25519"
    try:
        rotated_key = await service.rotate_active_key_metadata(rotated_key_id)
        assert rotated_key.key_id == rotated_key_id

        active_resp = await client.get(
            "/v1/signing-keys/active",
            headers=BOOTSTRAP_HEADERS,
        )
        assert active_resp.status_code == 200
        assert active_resp.json()["key_id"] == rotated_key_id

        new_permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name="current-tool",
            idem_key="permit-after-signing-key-rotation",
        )
        assert new_permit["key_id"] == rotated_key_id

        permit_verify = await client.post(
            "/v1/permits/verify",
            json={
                "permit_id": old_permit["permit_id"],
                "wallet_id": provisioned["agent_wallet_id"],
                "tool": "historical-tool",
                "estimated_credits": 1,
            },
            headers=provisioned["agent_headers"],
        )
        assert permit_verify.status_code == 200
        assert permit_verify.json()["valid"] is True

        receipt_verify = await client.post(
            "/v1/receipts/verify",
            json={"receipt_id": old_receipt.receipt_id},
            headers=provisioned["agent_headers"],
        )
        assert receipt_verify.status_code == 200
        assert receipt_verify.json()["valid"] is True

        audit_verify = await client.post(
            "/v1/audit/verify-chain",
            json={"wallet_id": provisioned["agent_wallet_id"]},
            headers=provisioned["agent_headers"],
        )
        assert audit_verify.status_code == 200
        assert audit_verify.json()["valid"] is True

        old_key_resp = await client.get(
            f"/v1/signing-keys/{old_permit['key_id']}",
            headers=BOOTSTRAP_HEADERS,
        )
        assert old_key_resp.status_code == 200
        assert old_key_resp.json()["status"] == "retired"
        assert old_key_resp.json()["retired_at"] is not None
        assert audit_event.signature_key_id == old_permit["key_id"]

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(SigningKeyModel).where(
                    SigningKeyModel.key_id.in_(
                        [old_permit["key_id"], rotated_key_id]
                    )
                )
            )
            statuses = {key.key_id: key.status for key in result.scalars().all()}
        assert statuses[old_permit["key_id"]] == "retired"
        assert statuses[rotated_key_id] == "active"
    finally:
        await service.rotate_active_key_metadata(original_key_id)
