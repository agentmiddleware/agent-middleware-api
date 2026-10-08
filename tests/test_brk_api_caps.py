"""Adversarial break-it tests for per-tool caps and daily limits.

Covers racing reserves under max_calls=1, daily-limit exhaustion mid-flight,
cap of 0, cap overflow, changing caps between reserve and finalize, and
atomic in-flight counting. Local test setups only.
"""

from __future__ import annotations

import asyncio
import json
from contextvars import ContextVar
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import PermitModel, WalletModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.idempotency import GOVERNED_MCP_IDEMPOTENCY_ENDPOINT
from app.services.idempotency import get_idempotency_service
from app.services.mcp_dispatch_attempts import get_mcp_dispatch_attempt_service
from app.services.permits import get_permit_service
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import BOOTSTRAP_HEADERS, provision_agent_wallet


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


@pytest.fixture
def echo_tool():
    tool_name = "brk-caps-echo"
    runs = {"count": 0}

    def echo(message: str = "ok") -> dict[str, Any]:
        runs["count"] += 1
        return {"message": message}

    get_service_registry().register_local(
        service_id=tool_name,
        name="Break caps echo",
        description="break-it echo tool",
        category=ServiceCategory.AGENT_COMMS,
        func=echo,
        credits_per_unit=2.0,
        unit_name="call",
    )
    try:
        yield tool_name, runs
    finally:
        get_service_registry().unregister_local(tool_name)


async def _permit_with_cap(
    client: AsyncClient,
    ctx: dict[str, Any],
    tool: str,
    *,
    cap: int,
    budget: int = 100,
    idem_key: str = "brk-cap-permit",
    extra: dict[str, Any] | None = None,
) -> str:
    body: dict[str, Any] = {
        "issuer_wallet_id": ctx["agent_wallet_id"],
        "subject_wallet_id": ctx["agent_wallet_id"],
        "subject_key_id": ctx["key_id"],
        "allowed_tools": [tool],
        "scopes": [f"tool:{tool}:invoke", "billing:charge"],
        "max_credits": budget,
        "max_calls_per_tool": {tool: cap},
        "expires_at": (utc_now() + timedelta(hours=1)).isoformat(),
    }
    if extra:
        body.update(extra)
    response = await client.post(
        "/v1/permits",
        json=body,
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": idem_key},
    )
    assert response.status_code == 201, response.text
    return response.json()["permit_id"]


async def _slot_state(permit_id: str) -> tuple[dict[str, Any], Decimal]:
    async with get_session_factory()() as session:
        permit = await session.get(PermitModel, permit_id)
        assert permit is not None
        return json.loads(permit.tool_call_counts_json or "{}"), permit.spent_credits


def _sync_upstream_validation_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hold two upstream reserves after their read-time validation."""
    dispatch_type = type(get_mcp_dispatch_attempt_service())
    permit_type = type(get_permit_service())
    original_prepare = dispatch_type.authorize_reserve_and_prepare
    original_validate = permit_type._validate_model_for_action
    in_prepare: ContextVar[bool] = ContextVar("brk_upstream_prepare", default=False)
    both_read = asyncio.Event()
    reads = 0

    async def prepare(self: Any, **kwargs: Any) -> Any:
        token = in_prepare.set(True)
        try:
            return await original_prepare(self, **kwargs)
        finally:
            in_prepare.reset(token)

    async def validate(self: Any, **kwargs: Any) -> Any:
        nonlocal reads
        result = await original_validate(self, **kwargs)
        if in_prepare.get():
            reads += 1
            if reads == 2:
                both_read.set()
            await asyncio.wait_for(both_read.wait(), timeout=10)
        return result

    monkeypatch.setattr(dispatch_type, "authorize_reserve_and_prepare", prepare)
    monkeypatch.setattr(permit_type, "_validate_model_for_action", validate)


@pytest.mark.anyio
async def test_race_two_upstream_reserves_cap1_admits_one(
    client: AsyncClient, clean_database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two concurrent remote reserves under max_calls=1 admit exactly one."""
    ctx = await provision_agent_wallet(client)
    wallet_id = ctx["agent_wallet_id"]
    tool = "brk.caps.remote.race"
    permit_id = await _permit_with_cap(
        client, ctx, tool, cap=1, idem_key="brk-race-permit"
    )
    _sync_upstream_validation_reads(monkeypatch)
    service = get_mcp_dispatch_attempt_service()

    async def reserve(suffix: str) -> Any:
        begun = await get_idempotency_service().begin_with_record(
            wallet_id=wallet_id,
            endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
            idempotency_key=f"brk-race-{suffix}",
            request_payload={"tool": tool, "arguments": {"message": suffix}},
            operation_kind="upstream_mcp",
        )
        return await service.authorize_reserve_and_prepare(
            idempotency_record_id=begun.record_id,
            wallet_id=wallet_id,
            permit_id=permit_id,
            key_id=ctx["key_id"],
            public_tool_id=tool,
            upstream_tool_name=tool,
            upstream_origin="https://test.example",
            request_hash=begun.request_hash,
            credits_authorized=Decimal("2"),
            arguments={"message": suffix},
        )

    (v1, a1), (v2, a2) = await asyncio.gather(reserve("alpha"), reserve("beta"))
    allowed = [v for v, _ in ((v1, a1), (v2, a2)) if v.allowed]
    denied = [v for v, _ in ((v1, a1), (v2, a2)) if not v.allowed]
    assert len(allowed) == 1
    assert len(denied) == 1
    assert denied[0].reason == "permit_max_calls_exceeded"
    attempts = [a for _, a in ((v1, a1), (v2, a2)) if a is not None]
    assert len(attempts) == 1
    counts, spent = await _slot_state(permit_id)
    assert counts == {tool: 1}
    assert spent == Decimal("2")


@pytest.mark.anyio
async def test_daily_limit_tightened_midflight_denies_and_unwinds(
    client: AsyncClient, clean_database: None, echo_tool: Any
) -> None:
    """A daily cap exhausted after reserve denies the charge and frees the slot."""
    tool, runs = echo_tool
    ctx = await provision_agent_wallet(client)
    wallet_id = ctx["agent_wallet_id"]
    permit_id = await _permit_with_cap(
        client, ctx, tool, cap=1, idem_key="brk-daily-permit"
    )

    def call_body(key: str, pid: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": f"call-{key}",
            "method": "tools/call",
            "params": {
                "name": tool,
                "arguments": {"message": "hello"},
                "mcpContext": {
                    "wallet_id": wallet_id,
                    "permit_id": pid,
                    "idempotency_key": key,
                },
            },
        }

    ok_response = await client.post(
        "/mcp/messages",
        json=call_body("brk-daily-ok", permit_id),
        headers=ctx["agent_headers"],
    )
    assert ok_response.status_code == 200, ok_response.text
    assert "error" not in ok_response.json(), ok_response.text
    assert runs["count"] == 1

    permit_id2 = await _permit_with_cap(
        client, ctx, tool, cap=1, idem_key="brk-daily-permit-2"
    )
    async with get_session_factory()() as session:
        async with session.begin():
            wallet = await session.get(WalletModel, wallet_id)
            assert wallet is not None
            wallet.daily_limit = Decimal("1")

    denied = await client.post(
        "/mcp/messages",
        json=call_body("brk-daily-denied", permit_id2),
        headers=ctx["agent_headers"],
    )
    assert denied.status_code == 200, denied.text
    body = denied.json()
    assert "error" in body, body
    # The wallet holds ~1000 credits, so with daily_limit=1 this denial can
    # only be the daily cap: the charge path reports it as insufficient_funds.
    assert body["error"]["message"] == "insufficient_funds", body
    assert runs["count"] == 1

    counts, spent = await _slot_state(permit_id2)
    assert spent == Decimal("0")
    assert counts.get(tool, 0) == 0

    async with get_session_factory()() as session:
        async with session.begin():
            wallet = await session.get(WalletModel, wallet_id)
            assert wallet is not None
            wallet.daily_limit = Decimal("500")

    retry = await client.post(
        "/mcp/messages",
        json=call_body("brk-daily-retry", permit_id2),
        headers=ctx["agent_headers"],
    )
    assert retry.status_code == 200, retry.text
    assert "error" not in retry.json(), retry.text
    assert runs["count"] == 2


@pytest.mark.anyio
async def test_cap_zero_and_negative_fail_closed(
    client: AsyncClient, clean_database: None, echo_tool: Any
) -> None:
    """A stored cap of 0 or below denies instead of admitting."""
    tool, _ = echo_tool
    ctx = await provision_agent_wallet(client)
    permit_id = await _permit_with_cap(
        client, ctx, tool, cap=1, idem_key="brk-zero-permit"
    )
    service = get_permit_service()

    for bad in (0, -1):
        async with get_session_factory()() as session:
            async with session.begin():
                model = await session.get(PermitModel, permit_id)
                assert model is not None
                model.max_calls_per_tool_json = json.dumps({tool: bad})
                model.tool_call_counts_json = None
                model.spent_credits = Decimal("0")
        validation = await service.authorize_and_reserve(
            permit_id=permit_id,
            wallet_id=ctx["agent_wallet_id"],
            tool_name=tool,
            estimated_credits=Decimal("2"),
            key_id=ctx["key_id"],
        )
        assert validation.allowed is False
        assert validation.reason == "permit_max_calls_exceeded"
        counts, spent = await _slot_state(permit_id)
        assert counts.get(tool, 0) == 0
        assert spent == Decimal("0")


@pytest.mark.anyio
async def test_cap_overflow_values_admit_and_count(
    client: AsyncClient, clean_database: None, echo_tool: Any
) -> None:
    """Huge caps behave like large finite limits with correct counting."""
    tool, _ = echo_tool
    ctx = await provision_agent_wallet(client)
    service = get_permit_service()
    for big in (2**31, 2**63, 10**30):
        created = await client.post(
            "/v1/permits",
            json={
                "issuer_wallet_id": ctx["agent_wallet_id"],
                "subject_wallet_id": ctx["agent_wallet_id"],
                "subject_key_id": ctx["key_id"],
                "allowed_tools": [tool],
                "scopes": [f"tool:{tool}:invoke", "billing:charge"],
                "max_credits": 100,
                "max_calls_per_tool": {tool: big},
                "expires_at": (utc_now() + timedelta(hours=1)).isoformat(),
            },
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": f"brk-big-{big}"},
        )
        assert created.status_code == 201, created.text
        permit_id = created.json()["permit_id"]
        for _ in range(2):
            validation = await service.authorize_and_reserve(
                permit_id=permit_id,
                wallet_id=ctx["agent_wallet_id"],
                tool_name=tool,
                estimated_credits=Decimal("1"),
                key_id=ctx["key_id"],
            )
            assert validation.allowed is True, validation.reason
        counts, spent = await _slot_state(permit_id)
        assert counts == {tool: 2}
        assert spent == Decimal("2")


@pytest.mark.anyio
async def test_cap_change_between_reserve_and_finalize(
    client: AsyncClient, clean_database: None, echo_tool: Any
) -> None:
    """Live cap edits apply to later reserves while earlier ones stand."""
    tool, _ = echo_tool
    ctx = await provision_agent_wallet(client)
    permit_id = await _permit_with_cap(
        client, ctx, tool, cap=2, budget=100, idem_key="brk-change-permit"
    )
    service = get_permit_service()

    async def reserve() -> Any:
        return await service.authorize_and_reserve(
            permit_id=permit_id,
            wallet_id=ctx["agent_wallet_id"],
            tool_name=tool,
            estimated_credits=Decimal("2"),
            key_id=ctx["key_id"],
        )

    first = await reserve()
    assert first.allowed is True, first.reason

    async with get_session_factory()() as session:
        async with session.begin():
            model = await session.get(PermitModel, permit_id)
            assert model is not None
            model.max_calls_per_tool_json = json.dumps({tool: 1})

    second = await reserve()
    assert second.allowed is False
    assert second.reason == "permit_max_calls_exceeded"

    async with get_session_factory()() as session:
        async with session.begin():
            model = await session.get(PermitModel, permit_id)
            assert model is not None
            model.max_credits = Decimal("1")

    third = await reserve()
    assert third.allowed is False
    assert third.reason == "permit_budget_exceeded"

    counts, spent = await _slot_state(permit_id)
    assert counts == {tool: 1}
    assert spent == Decimal("2")

    async with get_session_factory()() as session:
        async with session.begin():
            model = await session.get(PermitModel, permit_id)
            assert model is not None
            model.max_calls_per_tool_json = json.dumps({tool: 2})
            model.max_credits = Decimal("100")

    fourth = await reserve()
    assert fourth.allowed is True, fourth.reason
    counts, spent = await _slot_state(permit_id)
    assert counts == {tool: 2}
    assert spent == Decimal("4")


@pytest.mark.anyio
async def test_negative_estimate_denies_without_moving_budget(
    client: AsyncClient, clean_database: None, echo_tool: Any
) -> None:
    """A negative cost estimate is refused and never deflates the permit."""
    tool, _ = echo_tool
    ctx = await provision_agent_wallet(client)
    permit_id = await _permit_with_cap(
        client, ctx, tool, cap=5, budget=100, idem_key="brk-negative-permit"
    )
    service = get_permit_service()

    first = await service.authorize_and_reserve(
        permit_id=permit_id,
        wallet_id=ctx["agent_wallet_id"],
        tool_name=tool,
        estimated_credits=Decimal("4"),
        key_id=ctx["key_id"],
    )
    assert first.allowed is True, first.reason

    denied = await service.authorize_and_reserve(
        permit_id=permit_id,
        wallet_id=ctx["agent_wallet_id"],
        tool_name=tool,
        estimated_credits=Decimal("-5"),
        key_id=ctx["key_id"],
    )
    assert denied.allowed is False
    assert denied.reason == "permit_credits_invalid"
    counts, spent = await _slot_state(permit_id)
    assert spent == Decimal("4")
    assert counts == {tool: 1}

    from app.services.permits import PermitError

    with pytest.raises(PermitError):
        await service.reserve_budget(permit_id, Decimal("-5"))
    _, spent = await _slot_state(permit_id)
    assert spent == Decimal("4")


@pytest.mark.anyio
async def test_concurrent_aggregate_cap_counts_inflight(
    client: AsyncClient, clean_database: None, echo_tool: Any
) -> None:
    """Two concurrent reserves against an aggregate cap admit at most one."""
    tool, _ = echo_tool
    ctx = await provision_agent_wallet(client)
    response = await client.post(
        "/v1/permits",
        json={
            "issuer_wallet_id": ctx["agent_wallet_id"],
            "subject_wallet_id": ctx["agent_wallet_id"],
            "subject_key_id": ctx["key_id"],
            "allowed_tools": [tool],
            "scopes": [f"tool:{tool}:invoke", "billing:charge"],
            "max_credits": 100,
            "aggregate_value_cap": 5,
            "expires_at": (utc_now() + timedelta(hours=1)).isoformat(),
        },
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "brk-agg-permit"},
    )
    assert response.status_code == 201, response.text
    permit_id = response.json()["permit_id"]

    permit_type = type(get_permit_service())
    original_validate = permit_type._validate_model_for_action
    gate = asyncio.Event()
    entered = 0

    async def barrier_validate(self: Any, **kwargs: Any) -> Any:
        nonlocal entered
        result = await original_validate(self, **kwargs)
        entered += 1
        if entered == 2:
            gate.set()
        await asyncio.wait_for(gate.wait(), timeout=10)
        return result

    from pytest import MonkeyPatch

    with MonkeyPatch.context() as mp:
        mp.setattr(permit_type, "_validate_model_for_action", barrier_validate)
        service = get_permit_service()

        async def reserve_once() -> Any:
            return await service.authorize_and_reserve(
                permit_id=permit_id,
                wallet_id=ctx["agent_wallet_id"],
                tool_name=tool,
                estimated_credits=Decimal("3"),
                key_id=ctx["key_id"],
            )

        results = await asyncio.gather(reserve_once(), reserve_once())

    allowed = [r for r in results if r.allowed]
    denied = [r for r in results if not r.allowed]
    assert len(allowed) == 1
    assert len(denied) == 1
    assert denied[0].reason == "permit_aggregate_value_cap_exceeded"
    _, spent = await _slot_state(permit_id)
    assert spent == Decimal("3")
