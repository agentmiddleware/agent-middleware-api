"""Same idempotency key, different bodies, fired in parallel.

Regression for the Wallet Of Agents black-box report (2026-10-10): "same key +
different body was rejected, including 4 of 5 in a parallel race". The
ambiguity is whether the fifth mismatched body was ACCEPTED. These tests pin
the answer:

* When an original already owns the key (completed OR still in flight), every
  mismatched body in a parallel burst is rejected with the dedicated conflict
  (N of N), with no second dispatch or debit.
* When the race has no prior owner (all bodies distinct, fired together),
  exactly one body wins the key as its first claimant and every other body is
  rejected (N-1 of N). That is the "4 of 5": the fifth call was the
  legitimate original, not a mismatched body slipping past the check.

The claim is atomic because ``idempotency_records`` has a unique
(wallet_id, endpoint, idempotency_key) identity: the loser of the INSERT race
gets IntegrityError, re-reads the winner's row, and compares hashes
(``IdempotencyService.begin_with_record``). These run in one process against
SQLite; the PostgreSQL multiprocess proofs remain separate gates.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.db.database import get_session_factory
from app.db.models import IdempotencyRecordModel, LedgerEntryModel, PermitModel
from app.main import app
from app.services.idempotency import (
    IdempotencyConflictError,
    get_idempotency_service,
)
from app.services.service_registry import get_service_registry
from tests.test_mcp_upstream_governed import (
    FakeUpstreamExecutor,
    _call_body,
    _register_upstream,
)
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

pytestmark = pytest.mark.anyio

CONFLICT = {"code": -32009, "message": "idempotency_key_reused"}


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as caller:
        yield caller


@dataclass
class BlockingExecutor(FakeUpstreamExecutor):
    """Succeeds, but only after the test releases the in-flight dispatch."""

    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def call_tool(self, arguments: dict[str, Any], **kwargs: Any) -> Any:
        before_dispatch = kwargs["before_dispatch"]

        async def hold_after_claim() -> None:
            await before_dispatch()
            self.entered.set()
            await asyncio.wait_for(self.release.wait(), timeout=30)

        return await super().call_tool(
            arguments, **{**kwargs, "before_dispatch": hold_after_claim}
        )


async def _post(body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    # A separate client per contender, like separate agents on the wire.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as caller:
        response = await caller.post("/mcp/messages", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _burst(bodies, headers, monkeypatch) -> list[dict[str, Any]]:
    """Hold every request at the idempotency claim until all have arrived."""
    service = get_idempotency_service()
    original = service.begin_with_record
    arrivals: set[asyncio.Task[Any] | None] = set()
    ready = asyncio.Event()

    async def begin(**kwargs):
        arrivals.add(asyncio.current_task())
        if len(arrivals) == len(bodies):
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=10)
        return await original(**kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(service, "begin_with_record", begin)
        responses = await asyncio.wait_for(
            asyncio.gather(*(_post(body, headers) for body in bodies)), timeout=30
        )
    assert len(arrivals) == len(bodies), "the requested race never occurred"
    return responses


async def _money_state(wallet_id: str, permit_id: str) -> tuple[int, Decimal, int]:
    async with get_session_factory()() as session:
        debits = await session.scalar(
            select(func.count())
            .select_from(LedgerEntryModel)
            .where(
                LedgerEntryModel.wallet_id == wallet_id,
                LedgerEntryModel.action == "debit",
            )
        )
        permit = await session.get(PermitModel, permit_id)
        records = await session.scalar(
            select(func.count())
            .select_from(IdempotencyRecordModel)
            .where(
                IdempotencyRecordModel.wallet_id == wallet_id,
                IdempotencyRecordModel.endpoint == "/mcp/invoke",
            )
        )
    assert permit is not None
    return int(debits or 0), permit.spent_credits, int(records or 0)


async def _setup(client, tool: str, executor: FakeUpstreamExecutor):
    provisioned = await provision_agent_wallet(client)
    _register_upstream(tool, executor)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=tool,
    )
    return provisioned, permit


def _bodies(tool, provisioned, permit, key, messages):
    return [
        _call_body(
            tool_name=tool,
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=permit["permit_id"],
            idempotency_key=key,
            message=message,
        )
        for message in messages
    ]


@pytest.mark.parametrize("n", [5, 10])
async def test_service_claim_race_accepts_one_body_and_conflicts_the_rest(
    client, clean_database, n
):
    """N+1 distinct hashes race the raw claim: one owner, N conflicts."""
    wallet_id = (await provision_agent_wallet(client))["agent_wallet_id"]
    service = get_idempotency_service()
    ready = asyncio.Event()
    arrived = 0

    async def contender(index: int):
        nonlocal arrived
        arrived += 1
        if arrived == n + 1:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=10)
        try:
            return await service.begin_with_record(
                wallet_id=wallet_id,
                endpoint="/mcp/invoke",
                idempotency_key="race-key",
                request_payload={"tool_name": "t", "arguments": {"i": index}},
            )
        except IdempotencyConflictError as exc:
            return exc

    results = await asyncio.gather(*(contender(i) for i in range(n + 1)))
    owners = [r for r in results if not isinstance(r, Exception)]
    conflicts = [r for r in results if isinstance(r, IdempotencyConflictError)]
    assert len(owners) == 1, results
    assert owners[0].replay is None
    assert len(conflicts) == n, results
    assert all(str(c) == "idempotency_key_reused" for c in conflicts)


@pytest.mark.parametrize("n", [5, 10])
async def test_parallel_mismatched_bodies_after_completed_original_all_conflict(
    client, clean_database, monkeypatch, n
):
    tool = f"woa-mismatch-done-{n}"
    executor = FakeUpstreamExecutor("success")
    provisioned, permit = await _setup(client, tool, executor)
    headers = provisioned["agent_headers"]
    try:
        [original] = _bodies(tool, provisioned, permit, "mm-done", ["original"])
        first = await _post(original, headers)
        assert "result" in first, first

        mismatched = _bodies(
            tool, provisioned, permit, "mm-done", [f"changed-{i}" for i in range(n)]
        )
        responses = await _burst(mismatched, headers, monkeypatch)

        assert [r.get("error") for r in responses] == [CONFLICT] * n, responses
        assert executor.dispatch_count == len(executor.calls) == 1
        assert await _money_state(
            provisioned["agent_wallet_id"], permit["permit_id"]
        ) == (1, Decimal("2"), 1)
        assert (await _post(original, headers))["result"] == first["result"]
    finally:
        get_service_registry().unregister_local(tool)


@pytest.mark.parametrize("n", [5, 10])
async def test_parallel_mismatched_bodies_during_inflight_original_all_conflict(
    client, clean_database, monkeypatch, n
):
    """The original holds the key mid-dispatch; mismatches must not wait or win."""
    tool = f"woa-mismatch-live-{n}"
    executor = BlockingExecutor("success")
    provisioned, permit = await _setup(client, tool, executor)
    headers = provisioned["agent_headers"]
    try:
        [original] = _bodies(tool, provisioned, permit, "mm-live", ["original"])
        original_task = asyncio.create_task(_post(original, headers))
        await asyncio.wait_for(executor.entered.wait(), timeout=10)

        mismatched = _bodies(
            tool, provisioned, permit, "mm-live", [f"changed-{i}" for i in range(n)]
        )
        responses = await _burst(mismatched, headers, monkeypatch)
        assert [r.get("error") for r in responses] == [CONFLICT] * n, responses
        assert not original_task.done()

        executor.release.set()
        first = await asyncio.wait_for(original_task, timeout=10)
        assert "result" in first, first
        assert first["result"]["structuredContent"]["echo"] == {"message": "original"}
        assert executor.dispatch_count == len(executor.calls) == 1
        assert await _money_state(
            provisioned["agent_wallet_id"], permit["permit_id"]
        ) == (1, Decimal("2"), 1)
    finally:
        executor.release.set()
        get_service_registry().unregister_local(tool)


@pytest.mark.parametrize("n", [5, 10])
async def test_cold_race_of_distinct_bodies_has_one_winner_and_rest_conflict(
    client, clean_database, monkeypatch, n
):
    """No prior owner: the WoA "4 of 5" shape. One first claimant, N-1 conflicts."""
    tool = f"woa-mismatch-cold-{n}"
    executor = FakeUpstreamExecutor("success")
    provisioned, permit = await _setup(client, tool, executor)
    headers = provisioned["agent_headers"]
    try:
        bodies = _bodies(
            tool, provisioned, permit, "mm-cold", [f"body-{i}" for i in range(n)]
        )
        responses = await _burst(bodies, headers, monkeypatch)

        winners = [i for i, r in enumerate(responses) if "result" in r]
        assert len(winners) == 1, responses
        assert executor.dispatch_count == len(executor.calls) == 1
        winning_message = executor.calls[0]["arguments"]["message"]
        assert bodies[winners[0]]["params"]["arguments"]["message"] == winning_message
        losers = [r for i, r in enumerate(responses) if i != winners[0]]
        assert [r.get("error") for r in losers] == [CONFLICT] * (n - 1), responses
        assert await _money_state(
            provisioned["agent_wallet_id"], permit["permit_id"]
        ) == (1, Decimal("2"), 1)
    finally:
        get_service_registry().unregister_local(tool)
