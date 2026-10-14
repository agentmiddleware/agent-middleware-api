"""A denial under another tenant's permit is not that tenant's evidence.

Tenant C invoking with tenant A's permit id used to get a signed denial
receipt filed under ``permit_id=A's permit`` and ``wallet_id=C``. A could then
list it under its permit and open C's full audit event through the evidence
route. The denial itself must still happen and be audited; only the receipt
and A's read access to C's rows are refused.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.db.database import get_session_factory
from app.db.models import ReceiptModel
from app.main import app
from app.services.service_registry import get_service_registry
from tests.test_mcp_trust_mode import (
    _assert_denial_audited,
    _jsonrpc_body,
    _register_echo_tool,
    strict_trust_mode,  # noqa: F401 - pytest fixture
)
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

TOOL = "foreign-permit-denial-tool"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _receipts_for_permit(permit_id: str) -> list[ReceiptModel]:
    async with get_session_factory()() as session:
        rows = await session.execute(
            select(ReceiptModel).where(ReceiptModel.permit_id == permit_id)
        )
        return list(rows.scalars())


@pytest.mark.anyio
async def test_foreign_permit_denial_writes_no_receipt_under_victim_permit(
    client,
    clean_database,
    strict_trust_mode,  # noqa: F811
):
    owner = await provision_agent_wallet(client)
    intruder = await provision_agent_wallet(client)
    _register_echo_tool(TOOL)
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=owner["agent_wallet_id"],
            key_id=owner["key_id"],
            tool_name=TOOL,
        )
        resp = await client.post(
            "/mcp/messages",
            json=_jsonrpc_body(
                tool_name=TOOL,
                wallet_id=intruder["agent_wallet_id"],
                request_id="foreign-permit-call",
                permit_id=permit["permit_id"],
                idempotency_key="foreign-permit-idem",
            ),
            headers=intruder["agent_headers"],
        )
        body = resp.json()
        assert body["error"]["message"] == "permit_wallet_mismatch"
        assert "receipt" not in str(body["error"].get("data") or {})
        await _assert_denial_audited(
            wallet_id=intruder["agent_wallet_id"],
            tool_name=TOOL,
            reason="permit_wallet_mismatch",
        )
        assert await _receipts_for_permit(permit["permit_id"]) == []

        listed = await client.get(
            f"/v1/permits/{permit['permit_id']}/receipts",
            headers=owner["agent_headers"],
        )
        assert listed.status_code == 200
        assert listed.json()["total"] == 0
    finally:
        get_service_registry().unregister_local(TOOL)


@pytest.mark.anyio
async def test_permit_owner_cannot_read_other_wallet_receipt_naming_its_permit(
    client,
    clean_database,
    strict_trust_mode,  # noqa: F811
):
    """Rows written before the write-side fix must not stay readable."""
    owner = await provision_agent_wallet(client)
    intruder = await provision_agent_wallet(client)
    _register_echo_tool(TOOL)
    try:
        owner_permit = await create_tool_permit(
            client,
            wallet_id=owner["agent_wallet_id"],
            key_id=owner["key_id"],
            tool_name=TOOL,
            idem_key="owner-permit",
        )
        intruder_permit = await create_tool_permit(
            client,
            wallet_id=intruder["agent_wallet_id"],
            key_id=intruder["key_id"],
            tool_name=TOOL,
            idem_key="intruder-permit",
        )
        ok = await client.post(
            "/mcp/messages",
            json=_jsonrpc_body(
                tool_name=TOOL,
                wallet_id=intruder["agent_wallet_id"],
                request_id="intruder-own-call",
                permit_id=intruder_permit["permit_id"],
                idempotency_key="intruder-own-idem",
            ),
            headers=intruder["agent_headers"],
        )
        assert "result" in ok.json(), ok.json()
        [receipt] = await _receipts_for_permit(intruder_permit["permit_id"])
        # Simulate a legacy row: the intruder's receipt naming the owner's permit.
        async with get_session_factory()() as session:
            await session.execute(
                update(ReceiptModel)
                .where(ReceiptModel.receipt_id == receipt.receipt_id)
                .values(permit_id=owner_permit["permit_id"])
            )
            await session.commit()

        for path in (
            f"/v1/receipts/{receipt.receipt_id}",
            f"/v1/receipts/{receipt.receipt_id}/evidence",
            f"/v1/evidence/{receipt.receipt_id}",
        ):
            resp = await client.get(path, headers=owner["agent_headers"])
            assert resp.status_code == 404, (path, resp.status_code, resp.text)

        listed = await client.get(
            f"/v1/permits/{owner_permit['permit_id']}/receipts",
            headers=owner["agent_headers"],
        )
        assert listed.json()["total"] == 0

        # The receipt's own wallet still reads it.
        own = await client.get(
            f"/v1/receipts/{receipt.receipt_id}", headers=intruder["agent_headers"]
        )
        assert own.status_code == 200
    finally:
        get_service_registry().unregister_local(TOOL)
