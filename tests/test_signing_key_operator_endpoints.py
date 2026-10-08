"""Operator signing-key rotation, retirement, and listing endpoints.

Covers POST /v1/signing-keys/rotate, POST /v1/signing-keys/retire, and
GET /v1/signing-keys/ : bootstrap-admin gating, key-id validation, the
refusal to retire the key that is still signing, and the guarantee that
receipts signed before a rotation still verify afterwards under their
original kid.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.database import get_session_factory
from app.db.models import SigningKeyModel
from app.main import app
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


async def _active_key_id(client: AsyncClient) -> str:
    resp = await client.get("/v1/signing-keys/active", headers=BOOTSTRAP_HEADERS)
    assert resp.status_code == 200
    return resp.json()["key_id"]


async def _issue_receipt(client: AsyncClient, *, idem_key: str, tool: str):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=tool,
        idem_key=idem_key,
    )
    receipt = await get_receipt_service().create_receipt(
        permit_id=permit["permit_id"],
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool=tool,
        request_payload={"message": "before"},
        response_payload={"message": "after"},
        ledger_entry_id=None,
        credits_authorized=Decimal("2"),
        credits_charged=Decimal("0"),
        outcome="success",
        audit_event_id=None,
    )
    return provisioned, permit, receipt


@pytest.mark.anyio
async def test_rotate_requires_bootstrap_admin(client, clean_database):
    provisioned = await provision_agent_wallet(client)

    resp = await client.post(
        "/v1/signing-keys/rotate",
        json={"new_key_id": "operator-rotated-key"},
        headers=provisioned["agent_headers"],
    )
    assert resp.status_code == 403

    resp = await client.post(
        "/v1/signing-keys/rotate", json={"new_key_id": "operator-rotated-key"}
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_retire_and_list_require_bootstrap_admin_or_auth(client, clean_database):
    provisioned = await provision_agent_wallet(client)

    resp = await client.post(
        "/v1/signing-keys/retire",
        json={"key_id": "some-key"},
        headers=provisioned["agent_headers"],
    )
    assert resp.status_code == 403

    resp = await client.get("/v1/signing-keys/")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_rotate_validates_key_id(client, clean_database):
    for bad_id in ("", "has spaces", "has/slash", "x" * 65):
        resp = await client.post(
            "/v1/signing-keys/rotate",
            json={"new_key_id": bad_id},
            headers=BOOTSTRAP_HEADERS,
        )
        assert resp.status_code == 422, bad_id


@pytest.mark.anyio
async def test_rotate_flips_active_key_and_preserves_history(client, clean_database):
    service = get_signing_key_service()
    original_key_id = await _active_key_id(client)
    original, old_permit, old_receipt = await _issue_receipt(
        client, idem_key="permit-before-operator-rotation", tool="history-tool"
    )

    rotated_key_id = "operator-rotated-ed25519"
    try:
        resp = await client.post(
            "/v1/signing-keys/rotate",
            json={"new_key_id": rotated_key_id},
            headers=BOOTSTRAP_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["key_id"] == rotated_key_id
        assert body["status"] == "active"
        assert body["public_key_b64"]
        assert "private" not in resp.text

        assert await _active_key_id(client) == rotated_key_id

        old_key_resp = await client.get(
            f"/v1/signing-keys/{old_permit['key_id']}", headers=BOOTSTRAP_HEADERS
        )
        assert old_key_resp.status_code == 200
        assert old_key_resp.json()["status"] == "retired"

        # New permits sign under the rotated kid.
        provisioned = await provision_agent_wallet(client)
        new_permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name="current-tool",
            idem_key="permit-after-operator-rotation",
        )
        assert new_permit["key_id"] == rotated_key_id

        # History still verifies under the retired kid.
        receipt_verify = await client.post(
            "/v1/receipts/verify",
            json={"receipt_id": old_receipt.receipt_id},
            headers=original["agent_headers"],
        )
        assert receipt_verify.status_code == 200
        assert receipt_verify.json()["valid"] is True
    finally:
        await service.rotate_active_key_metadata(original_key_id)


@pytest.mark.anyio
async def test_rotate_rejects_key_id_bound_to_different_material(
    client, clean_database
):
    active_before = await _active_key_id(client)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            SigningKeyModel(
                key_id="foreign-material-key",
                public_key_b64="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
                status="retired",
            )
        )
        await session.commit()

    resp = await client.post(
        "/v1/signing-keys/rotate",
        json={"new_key_id": "foreign-material-key"},
        headers=BOOTSTRAP_HEADERS,
    )
    assert resp.status_code == 409
    assert await _active_key_id(client) == active_before


@pytest.mark.anyio
async def test_retire_non_active_key_keeps_it_verifiable(client, clean_database):
    service = get_signing_key_service()
    original_key_id = await _active_key_id(client)
    original, old_permit, old_receipt = await _issue_receipt(
        client, idem_key="permit-before-operator-retire", tool="retire-tool"
    )

    rotated_key_id = "operator-retire-successor"
    try:
        resp = await client.post(
            "/v1/signing-keys/rotate",
            json={"new_key_id": rotated_key_id},
            headers=BOOTSTRAP_HEADERS,
        )
        assert resp.status_code == 200

        resp = await client.post(
            "/v1/signing-keys/retire",
            json={"key_id": old_permit["key_id"]},
            headers=BOOTSTRAP_HEADERS,
        )
        # Already retired by the rotation above: the retire call is idempotent.
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "retired"

        receipt_verify = await client.post(
            "/v1/receipts/verify",
            json={"receipt_id": old_receipt.receipt_id},
            headers=original["agent_headers"],
        )
        assert receipt_verify.status_code == 200
        assert receipt_verify.json()["valid"] is True

        listed = await client.get("/v1/signing-keys/", headers=BOOTSTRAP_HEADERS)
        assert listed.status_code == 200
        statuses = {key["key_id"]: key["status"] for key in listed.json()["keys"]}
        assert statuses[old_permit["key_id"]] == "retired"
        assert statuses[rotated_key_id] == "active"
    finally:
        await service.rotate_active_key_metadata(original_key_id)


@pytest.mark.anyio
async def test_retire_active_key_is_refused(client, clean_database):
    active_key_id = await _active_key_id(client)

    resp = await client.post(
        "/v1/signing-keys/retire",
        json={"key_id": active_key_id},
        headers=BOOTSTRAP_HEADERS,
    )
    assert resp.status_code == 409

    assert await _active_key_id(client) == active_key_id


@pytest.mark.anyio
async def test_retire_unknown_key_returns_404(client, clean_database):
    resp = await client.post(
        "/v1/signing-keys/retire",
        json={"key_id": "key-that-was-never-published"},
        headers=BOOTSTRAP_HEADERS,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_list_keys_requires_authentication(client, clean_database):
    for headers, expected in (
        ({}, 401),
        ({"X-API-Key": "short"}, 401),
        ({"X-API-Key": "not-a-real-key"}, 403),
    ):
        resp = await client.get("/v1/signing-keys/", headers=headers)
        assert resp.status_code == expected, resp.text
        assert "public_key_b64" not in resp.text
