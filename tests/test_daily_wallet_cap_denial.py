"""Daily wallet cap reached -> signed denial receipt, zero charged, no dispatch.

Wallet Of Agents (2026-10-10) did not reach the daily wallet cap in prod. The
only hard daily-spend enforcement is the charge-time check in
``app/services/billing_engine.py`` (the velocity monitor only alerts), and for
the upstream path it runs before the one-shot send right is claimed. So a call
over the cap must be refused with a verifiable signed receipt, move no money,
release its permit reservation, never reach the upstream, and replay
identically under the same key.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.db.database import get_session_factory
from app.db.models import LedgerEntryModel, PermitModel, WalletModel
from app.main import app
from app.services.receipts import get_receipt_service
from app.services.service_registry import get_service_registry
from tests.test_mcp_upstream_governed import (
    FakeUpstreamExecutor,
    _call_body,
    _register_upstream,
)
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as caller:
        yield caller


@pytest.mark.parametrize("daily_limit", ["0", "2"])
async def test_daily_cap_reached_returns_signed_zero_charge_denial(
    client, clean_database, daily_limit
):
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    headers = provisioned["agent_headers"]
    async with get_session_factory()() as session:
        wallet = await session.get(WalletModel, wallet_id)
        assert wallet is not None
        wallet.daily_limit = Decimal(daily_limit)
        await session.commit()
    tool = f"daily-cap-{daily_limit}"
    executor = FakeUpstreamExecutor("success")
    _register_upstream(tool, executor)  # 2 credits per call
    try:
        permit = await create_tool_permit(
            client, wallet_id=wallet_id, key_id=provisioned["key_id"], tool_name=tool
        )

        def body(key: str):
            return _call_body(
                tool_name=tool,
                wallet_id=wallet_id,
                permit_id=permit["permit_id"],
                idempotency_key=key,
            )

        allowed_calls = int(Decimal(daily_limit) // 2)
        for index in range(allowed_calls):
            ok = await client.post(
                "/mcp/messages", json=body(f"under-cap-{index}"), headers=headers
            )
            assert "result" in ok.json(), ok.text

        over = await client.post(
            "/mcp/messages", json=body("over-cap"), headers=headers
        )
        assert over.status_code == 200
        error = over.json()["error"]
        assert error["code"] == -32004
        assert error["message"] == "insufficient_funds"
        receipt = error["data"]["receipt"]
        # Upstream-path denials after the attempt row exists are receipted as
        # failed_refunded with the real cause in reason_code (see the
        # InsufficientFundsResponse branch in app/routers/mcp.py). Nothing
        # was charged, so nothing was actually refunded.
        assert receipt["outcome"] == "failed_refunded"
        assert receipt["reason_code"] == "insufficient_funds"
        assert Decimal(receipt["credits_charged"]) == 0
        assert receipt["ledger_entry_id"] is None
        assert receipt["permit_id"] == permit["permit_id"]
        ok_sig, reason, _ = await get_receipt_service().verify_receipt(
            receipt["receipt_id"]
        )
        assert ok_sig, reason
        assert executor.dispatch_count == len(executor.calls) == allowed_calls

        replay = await client.post(
            "/mcp/messages", json=body("over-cap"), headers=headers
        )
        assert replay.json()["error"] == error
        assert executor.dispatch_count == allowed_calls

        spent = Decimal(2 * allowed_calls)
        async with get_session_factory()() as session:
            wallet = await session.get(WalletModel, wallet_id)
            stored_permit = await session.get(PermitModel, permit["permit_id"])
            debits = await session.scalar(
                select(func.count())
                .select_from(LedgerEntryModel)
                .where(
                    LedgerEntryModel.wallet_id == wallet_id,
                    LedgerEntryModel.action == "debit",
                )
            )
        assert wallet is not None and stored_permit is not None
        assert wallet.balance == Decimal("1000") - spent
        assert wallet.daily_spent == spent
        # The refused call's reservation was handed back, not held.
        assert stored_permit.spent_credits == spent
        assert debits == allowed_calls
    finally:
        get_service_registry().unregister_local(tool)
