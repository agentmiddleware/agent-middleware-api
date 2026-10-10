"""Literal WoA race counts and daily boundaries using the governed upstream path.

These use separate ASGI clients and database sessions in one process. PostgreSQL
multiprocess and hosted partner proofs remain separate acceptance gates.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import (
    LedgerEntryModel,
    McpDispatchAttemptModel,
    PermitModel,
    WalletModel,
)
from app.main import app
from app.services import velocity_monitor
from app.services.idempotency import get_idempotency_service
from app.services.service_registry import get_service_registry
from tests.test_mcp_upstream_governed import (
    FakeUpstreamExecutor,
    _assert_linked_terminal_state,
    _call_body,
    _load_persisted_invocation,
    _register_upstream,
)
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

pytestmark = [pytest.mark.anyio, pytest.mark.dormant]


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as caller:
        yield caller


async def _race(bodies, headers, monkeypatch):
    """Hold the first entry from each request until every contender has arrived."""
    service = get_idempotency_service()
    original = service.begin_with_record
    arrivals = set()
    ready = asyncio.Event()

    async def begin(**kwargs):
        arrivals.add(asyncio.current_task())
        if len(arrivals) == len(bodies):
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=10)
        return await original(**kwargs)

    async def submit(body):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as caller:
            return await caller.post("/mcp/messages", json=body, headers=headers)

    with monkeypatch.context() as patch:
        patch.setattr(service, "begin_with_record", begin)
        responses = await asyncio.wait_for(
            asyncio.gather(*(submit(body) for body in bodies)), timeout=30
        )
    assert len(arrivals) == len(bodies), "the requested race never occurred"
    assert all(response.status_code == 200 for response in responses)
    return [response.json() for response in responses]


@pytest.mark.parametrize("mixed", [False, True], ids=["ten-identical", "five-bodies"])
async def test_simultaneous_key_reuse_has_one_dispatch_and_debit(
    client, clean_database, monkeypatch, mixed
):
    provisioned = await provision_agent_wallet(client)
    tool = "woa-race"
    executor = FakeUpstreamExecutor("success")
    _register_upstream(tool, executor)
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool,
        )
        bodies = [
            _call_body(
                tool_name=tool,
                wallet_id=provisioned["agent_wallet_id"],
                permit_id=permit["permit_id"],
                idempotency_key="woa-race-key",
                message=str(index) if mixed else "same",
            )
            for index in range(5 if mixed else 10)
        ]
        responses = await _race(bodies, provisioned["agent_headers"], monkeypatch)
        assert any("result" in response for response in responses)
        assert executor.dispatch_count == len(executor.calls) == 1
        winner = executor.calls[0]["arguments"]["message"]
        first_result = next(
            response["result"] for response in responses if "result" in response
        )
        for body, response in zip(bodies, responses):
            if "result" in response:
                assert response["result"] == first_result
                assert body["params"]["arguments"]["message"] == winner
            else:
                if body["params"]["arguments"]["message"] == winner:
                    assert response["error"] == {
                        "code": -32005,
                        "message": "idempotency_in_progress",
                    }
                else:
                    assert response["error"] == {
                        "code": -32009,
                        "message": "idempotency_key_reused",
                    }
            replay = await client.post(
                "/mcp/messages", json=body, headers=provisioned["agent_headers"]
            )
            if body["params"]["arguments"]["message"] == winner:
                assert replay.json()["result"] == first_result
            else:
                assert replay.json()["error"] == {
                    "code": -32009,
                    "message": "idempotency_key_reused",
                }
        persisted = await _load_persisted_invocation(
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=permit["permit_id"],
            idempotency_key="woa-race-key",
        )
        _assert_linked_terminal_state(
            persisted,
            state="succeeded",
            outcome="success",
            charged=Decimal("2"),
            refunded=False,
        )
        assert executor.dispatch_count == len(executor.calls) == 1
    finally:
        get_service_registry().unregister_local(tool)


async def test_parallel_daily_boundary_replays_at_cap_and_resets(
    client, clean_database, monkeypatch
):
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    now = utc_now()
    monkeypatch.setattr(velocity_monitor, "utc_now", lambda: now)
    async with get_session_factory()() as session:
        wallet = await session.get(WalletModel, wallet_id)
        assert wallet is not None
        wallet.daily_limit = Decimal("4")
        wallet.hourly_limit = Decimal("1000")
        wallet.daily_reset_at = now.replace(hour=0, minute=0, second=0, microsecond=0)
        await session.commit()
    tool = "woa-daily-cap"
    executor = FakeUpstreamExecutor("success")
    _register_upstream(tool, executor)
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=wallet_id,
            key_id=provisioned["key_id"],
            tool_name=tool,
        )
        bodies = [
            _call_body(
                tool_name=tool,
                wallet_id=wallet_id,
                permit_id=permit["permit_id"],
                idempotency_key=f"woa-daily-{index}",
            )
            for index in range(5)
        ]
        responses = await _race(bodies, provisioned["agent_headers"], monkeypatch)
        assert sum("result" in response for response in responses) == 2
        assert executor.dispatch_count == len(executor.calls) == 2
        for body, response in zip(bodies, responses):
            if "error" in response:
                assert response["error"]["message"] == "insufficient_funds"
                assert response["error"]["data"]["receipt"]["credits_charged"] == "0"
            replay = await client.post(
                "/mcp/messages", json=body, headers=provisioned["agent_headers"]
            )
            assert replay.json() == response
        async with get_session_factory()() as session:
            wallet = await session.get(WalletModel, wallet_id)
            assert wallet is not None
            assert wallet.daily_spent == Decimal("4")
            assert wallet.balance == Decimal("996")
            stored_permit = await session.get(PermitModel, permit["permit_id"])
            assert stored_permit is not None
            assert stored_permit.spent_credits == Decimal("4")
            debits = list(
                (
                    await session.execute(
                        select(LedgerEntryModel).where(
                            LedgerEntryModel.wallet_id == wallet_id,
                            LedgerEntryModel.action == "debit",
                        )
                    )
                ).scalars()
            )
            attempts = list(
                (
                    await session.execute(
                        select(McpDispatchAttemptModel).where(
                            McpDispatchAttemptModel.wallet_id == wallet_id,
                            McpDispatchAttemptModel.dispatched_at.is_not(None),
                        )
                    )
                ).scalars()
            )
            assert len(debits) == len(attempts) == 2
        assert executor.dispatch_count == 2
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
            days=1
        )
        monkeypatch.setattr(velocity_monitor, "utc_now", lambda: tomorrow)
        next_body = _call_body(
            tool_name=tool,
            wallet_id=wallet_id,
            permit_id=permit["permit_id"],
            idempotency_key="woa-next-day",
        )
        next_response = await client.post(
            "/mcp/messages", json=next_body, headers=provisioned["agent_headers"]
        )
        assert "result" in next_response.json()
        async with get_session_factory()() as session:
            wallet = await session.get(WalletModel, wallet_id)
            assert wallet is not None
            assert wallet.daily_spent == Decimal("2")
            assert wallet.daily_reset_at == tomorrow
            assert wallet.balance == Decimal("994")
            stored_permit = await session.get(PermitModel, permit["permit_id"])
            assert stored_permit is not None
            assert stored_permit.spent_credits == Decimal("6")
        assert executor.dispatch_count == len(executor.calls) == 3
    finally:
        get_service_registry().unregister_local(tool)
