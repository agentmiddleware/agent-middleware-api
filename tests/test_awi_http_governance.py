"""AWI HTTP high-risk routes must require permit → meter → receipt."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from httpx import ASGITransport, AsyncClient

from app.db.database import get_session_factory
from app.db.models import IdempotencyRecordModel, LedgerEntryModel
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
async def test_rag_query_denied_without_permit(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    resp = await client.post(
        "/v1/awi/rag/query",
        json={"query": "laptops", "top_k": 3},
        headers={
            **provisioned["agent_headers"],
            "X-Wallet-Id": provisioned["agent_wallet_id"],
        },
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "permit_required"


@pytest.mark.anyio
async def test_rag_query_succeeds_with_permit_and_receipt(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="awi_rag_query",
        max_credits=50,
        idem_key="permit-awi-http-rag",
    )
    resp = await client.post(
        "/v1/awi/rag/query",
        json={"query": "laptops", "top_k": 3},
        headers={
            **provisioned["agent_headers"],
            "X-Wallet-Id": provisioned["agent_wallet_id"],
            "X-Permit-Id": permit["permit_id"],
            "Idempotency-Key": "awi-http-rag-1",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "laptops"
    assert "results" in body
    assert body["receipt"]["permit_id"] == permit["permit_id"]
    assert body["receipt"]["outcome"] == "success"
    assert body["receipt"]["signature"]

    receipt_resp = await client.get(
        f"/v1/receipts/{body['receipt']['receipt_id']}",
        headers=provisioned["agent_headers"],
    )
    assert receipt_resp.status_code == 200, receipt_resp.text
    receipt = receipt_resp.json()
    assert Decimal(str(receipt["credits_authorized"])) == Decimal("3")
    assert Decimal(str(receipt["credits_charged"])) == Decimal("3")
    assert receipt["ledger_entry_id"]


@pytest.mark.anyio
async def test_rag_query_insufficient_funds_aborts_and_replays(client, clean_database):
    """402 closes the idempotency key; same key replays 402 (not 409 in-progress)."""
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="awi_rag_query",
        max_credits=50,
        idem_key="permit-awi-broke",
    )

    # Leave the agent with 2 credits (rag costs 3) after permit creation.
    transfer = await client.post(
        "/v1/billing/transfer",
        params={
            "from_wallet_id": provisioned["agent_wallet_id"],
            "to_wallet_id": provisioned["sponsor_wallet_id"],
            "amount": 998,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert transfer.status_code == 200, transfer.text

    headers = {
        **provisioned["agent_headers"],
        "X-Wallet-Id": provisioned["agent_wallet_id"],
        "X-Permit-Id": permit["permit_id"],
        "Idempotency-Key": "awi-http-broke-1",
    }
    payload = {"query": "laptops", "top_k": 3}

    first = await client.post("/v1/awi/rag/query", json=payload, headers=headers)
    assert first.status_code == 402, first.text
    assert first.json()["detail"]["error"] == "insufficient_funds"

    second = await client.post("/v1/awi/rag/query", json=payload, headers=headers)
    assert second.status_code == 402, second.text
    assert second.json()["detail"]["error"] == "insufficient_funds"


@pytest.mark.anyio
async def test_execute_denied_without_wallet_scoped_session(client, clean_database):
    """Sessions without wallet_id cannot enter the governed execute path."""
    create = await client.post(
        "/v1/awi/sessions",
        json={"target_url": "https://example.com"},
        headers={"X-API-Key": "test-key"},
    )
    assert create.status_code == 201
    session_id = create.json()["session_id"]

    resp = await client.post(
        "/v1/awi/execute",
        json={
            "session_id": session_id,
            "action": "navigate_to",
            "parameters": {"url": "https://example.com/next"},
        },
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "wallet_required"


@pytest.mark.anyio
async def test_awi_route_keys_its_debit_to_the_idempotency_record(
    client, clean_database
):
    """The governed AWI route must key its debit to the request's identity.

    This path used to call ``money.charge()`` with no ``operation_key``, so it
    had neither the ``uq_ledger_wallet_operation_key`` constraint nor the
    adopt-the-existing-debit recovery the governed MCP path relies on. A charge
    that committed but whose acknowledgement was lost took the failure branch,
    which releases the permit budget and *completes* the idempotency record as
    ``charge_failed`` -- so the caller retried under a fresh key and paid twice
    for one logical action.

    Asserted on the real route rather than on ``money.charge`` directly,
    because the defect was the wiring: the mechanism already existed and this
    caller simply did not use it.
    """
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="awi_rag_query",
        max_credits=50,
        idem_key="permit-awi-opkey",
    )
    resp = await client.post(
        "/v1/awi/rag/query",
        json={"query": "laptops", "top_k": 3},
        headers={
            **provisioned["agent_headers"],
            "X-Wallet-Id": provisioned["agent_wallet_id"],
            "X-Permit-Id": permit["permit_id"],
            "Idempotency-Key": "awi-opkey-1",
        },
    )
    assert resp.status_code == 200, resp.text

    factory = get_session_factory()
    async with factory() as session:
        record_id = (
            await session.execute(
                select(IdempotencyRecordModel.record_id).where(
                    IdempotencyRecordModel.wallet_id == provisioned["agent_wallet_id"],
                    IdempotencyRecordModel.idempotency_key == "awi-opkey-1",
                )
            )
        ).scalar_one()
        keyed = (
            await session.execute(
                select(func.count())
                .select_from(LedgerEntryModel)
                .where(LedgerEntryModel.operation_key == record_id)
            )
        ).scalar_one()
        unkeyed = (
            await session.execute(
                select(func.count())
                .select_from(LedgerEntryModel)
                .where(
                    LedgerEntryModel.wallet_id == provisioned["agent_wallet_id"],
                    # Debits are written as action="debit" with a negative
                    # amount (LedgerEntryModel: "Positive = credit, negative =
                    # debit"). Select by sign so this counts real debits.
                    LedgerEntryModel.amount < 0,
                    LedgerEntryModel.operation_key.is_(None),
                )
            )
        ).scalar_one()

    assert keyed == 1, (
        "the AWI debit is not keyed to its idempotency record, so a retry "
        "after a lost acknowledgement would debit again"
    )
    assert unkeyed == 0, "a governed AWI charge landed with no operation_key"
