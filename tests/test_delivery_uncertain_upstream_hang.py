"""Public, reproducible upstream-hang regression for ``delivery_uncertain``.

Wallet Of Agents black-box tested AMW prod on 2026-10-10 and could not reach
the delivery_uncertain path. This reproduces it with no mocks inside the
gateway: a real FastMCP server whose tool hangs past the configured call
timeout, reached through the real ``UpstreamMcpAdapter`` (streamable HTTP over
an in-process ASGI transport), invoked through ``/mcp/messages``.

The required outcome is PARKED, not failed: once the gateway has claimed the
one-shot send right and the upstream goes silent, the action may have happened.
So the call must

* finalize as ``delivery_uncertain`` (attempt state + signed receipt outcome),
* keep the hold (charge stands, permit budget stays reserved),
* never auto-fail or auto-refund, including after the reconciliation sweep,
* never mint a fresh key or redispatch: a same-key retry replays the exact
  response, and there is at most one debit.

The exact request/response pair lives in
``tests/fixtures/replay/delivery_uncertain_upstream_hang.json`` so any change to
the wire contract shows up as a fixture diff.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import func, select, update

from app.core.config import Settings
from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import (
    IdempotencyRecordModel,
    LedgerEntryModel,
    McpDispatchAttemptModel,
    PermitModel,
    ReceiptModel,
    WalletModel,
)
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.idempotency import get_idempotency_service
from app.services.mcp_dispatch_reconciliation import (
    get_mcp_dispatch_reconciliation_service,
)
from app.services.receipts import get_receipt_service
from app.services.service_registry import get_service_registry
from app.services.upstream_mcp import UpstreamMcpAdapter, UpstreamMcpConfiguration
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet

pytestmark = pytest.mark.anyio

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "replay"
    / "delivery_uncertain_upstream_hang.json"
)
TOOL = "partner.hang.write"
CALL_TIMEOUT_SECONDS = 0.5
TOKEN = "hang-fixture-partner-token"
# Fixture placeholders. "<any>" matches any non-empty value; the named ones
# must equal the value this run produced.
ANY = "<any>"


def _substitute(value: Any, names: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: _substitute(v, names) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, names) for v in value]
    if isinstance(value, str) and value in names:
        return names[value]
    return value


def _assert_matches(actual: Any, expected: Any, path: str = "$") -> None:
    if expected == ANY:
        assert actual not in (None, "", [], {}), f"{path}: expected a value"
        return
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: {actual!r}"
        assert set(actual) == set(expected), (
            f"{path}: keys {sorted(actual)} != {sorted(expected)}"
        )
        for key in expected:
            _assert_matches(actual[key], expected[key], f"{path}.{key}")
        return
    assert actual == expected, f"{path}: {actual!r} != {expected!r}"


class HangingUpstream:
    """A real MCP server whose one tool never answers within the timeout."""

    def __init__(self) -> None:
        self.calls = 0
        self.unblock = asyncio.Event()
        server = FastMCP(
            "partner-hang",
            stateless_http=True,
            json_response=True,
            transport_security=TransportSecuritySettings(
                allowed_hosts=["localhost:9000"]
            ),
        )

        @server.tool(name="partner.write", description="Hangs past the timeout")
        async def partner_write(note: str) -> dict[str, str]:
            self.calls += 1
            await self.unblock.wait()
            return {"echo": note}

        self.app = server.streamable_http_app()


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as caller:
        yield caller


@pytest.fixture
async def hanging_upstream():
    upstream = HangingUpstream()
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=upstream.app),
        base_url="http://localhost",
        headers={"Authorization": f"Bearer {TOKEN}"},
        follow_redirects=False,
    )
    configuration = UpstreamMcpConfiguration.from_settings(
        Settings(
            _env_file=None,
            ENVIRONMENT="local",
            MCP_UPSTREAM_ENABLED=True,
            MCP_UPSTREAM_URL="http://localhost:9000/mcp",
            MCP_UPSTREAM_TOOL_NAME="partner.write",
            MCP_UPSTREAM_PUBLIC_TOOL_ID=TOOL,
            MCP_UPSTREAM_BEARER_TOKEN=TOKEN,
            MCP_UPSTREAM_CREDITS_PER_CALL="2",
            MCP_UPSTREAM_CALL_TIMEOUT_SECONDS=CALL_TIMEOUT_SECONDS,
        )
    )
    adapter = UpstreamMcpAdapter(configuration, http_client=http_client)
    async with upstream.app.router.lifespan_context(upstream.app):
        discovered = await adapter.discover_tool()
        get_service_registry().register_upstream(
            service_id=TOOL,
            name=discovered.name,
            description=discovered.description,
            category=ServiceCategory.AGENT_COMMS,
            executor=adapter,
            input_schema=discovered.input_schema,
            output_schema=discovered.output_schema,
            credits_per_unit=2.0,
            upstream_tool_name="partner.write",
            upstream_origin=configuration.origin,
        )
        try:
            yield upstream
        finally:
            upstream.unblock.set()
            get_service_registry().unregister_local(TOOL)
    await http_client.aclose()


async def _state(wallet_id: str, permit_id: str) -> dict[str, Any]:
    async with get_session_factory()() as session:

        async def count(model, *where) -> int:
            return int(
                await session.scalar(
                    select(func.count()).select_from(model).where(*where)
                )
                or 0
            )

        attempt = (
            await session.execute(
                select(McpDispatchAttemptModel).where(
                    McpDispatchAttemptModel.wallet_id == wallet_id
                )
            )
        ).scalar_one()
        permit = await session.get(PermitModel, permit_id)
        wallet = await session.get(WalletModel, wallet_id)
        receipt = (
            await session.execute(
                select(ReceiptModel).where(
                    ReceiptModel.dispatch_attempt_id == attempt.attempt_id
                )
            )
        ).scalar_one()
        return {
            "attempt_state": attempt.state,
            "attempt_dispatched": attempt.dispatched_at is not None,
            "attempt_refunded": attempt.debit_refunded_at is not None,
            "budget_released": attempt.budget_released_at is not None,
            "receipt_outcome": receipt.outcome,
            "receipt_charged": str(receipt.credits_charged.normalize()),
            "permit_spent": str(permit.spent_credits.normalize()),
            "wallet_balance": str(wallet.balance.normalize()),
            "debits": await count(
                LedgerEntryModel,
                LedgerEntryModel.wallet_id == wallet_id,
                LedgerEntryModel.action == "debit",
            ),
            "refunds": await count(
                LedgerEntryModel,
                LedgerEntryModel.wallet_id == wallet_id,
                LedgerEntryModel.action == "refund",
            ),
            "invoke_records": await count(
                IdempotencyRecordModel,
                IdempotencyRecordModel.wallet_id == wallet_id,
                IdempotencyRecordModel.endpoint == "/mcp/invoke",
            ),
        }


PARKED = {
    "attempt_state": "delivery_uncertain",
    "attempt_dispatched": True,
    "attempt_refunded": False,
    "budget_released": False,
    "receipt_outcome": "delivery_uncertain",
    "receipt_charged": "2",
    "permit_spent": "2",
    "wallet_balance": "998",
    "debits": 1,
    "refunds": 0,
    "invoke_records": 1,
}


async def test_upstream_hang_parks_as_delivery_uncertain_matching_named_fixture(
    client, clean_database, hanging_upstream
):
    fixture = json.loads(FIXTURE.read_text())
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    permit = await create_tool_permit(
        client, wallet_id=wallet_id, key_id=provisioned["key_id"], tool_name=TOOL
    )
    names = {
        "<wallet_id>": wallet_id,
        "<permit_id>": permit["permit_id"],
        "<key_id>": provisioned["key_id"],
    }
    request = _substitute(fixture["request"], names)

    response = await client.post(
        "/mcp/messages", json=request, headers=provisioned["agent_headers"]
    )
    assert response.status_code == fixture["response_status"]
    body = response.json()
    _assert_matches(body, _substitute(fixture["response"], names))
    assert hanging_upstream.calls == 1
    assert await _state(wallet_id, permit["permit_id"]) == PARKED

    receipt = body["error"]["data"]["receipt"]
    assert (
        receipt["dispatch_attempt_id"]
        == body["error"]["data"]["dispatch"]["attempt_id"]
    )
    ok, reason, _ = await get_receipt_service().verify_receipt(receipt["receipt_id"])
    assert ok, reason

    # Same-key retry: identical bytes, no fresh key, no redispatch, no debit.
    retry = await client.post(
        "/mcp/messages", json=request, headers=provisioned["agent_headers"]
    )
    assert retry.status_code == response.status_code
    assert retry.json() == body
    assert hanging_upstream.calls == 1
    assert await _state(wallet_id, permit["permit_id"]) == PARKED

    # Long after the fact, the sweeps still must not fail or refund it.
    stale = utc_now() - timedelta(days=2)
    async with get_session_factory()() as session:
        await session.execute(
            update(McpDispatchAttemptModel)
            .where(McpDispatchAttemptModel.wallet_id == wallet_id)
            .values(created_at=stale, updated_at=stale)
        )
        await session.execute(
            update(IdempotencyRecordModel)
            .where(IdempotencyRecordModel.wallet_id == wallet_id)
            .values(created_at=stale)
        )
        await session.commit()
    await get_mcp_dispatch_reconciliation_service().reconcile(terminal_idle_seconds=0)
    await get_idempotency_service().reconcile_stuck_records(idle_seconds=0)
    assert await _state(wallet_id, permit["permit_id"]) == PARKED
    late = await client.post(
        "/mcp/messages", json=request, headers=provisioned["agent_headers"]
    )
    assert late.json() == body
    assert hanging_upstream.calls == 1


async def test_same_key_retry_while_upstream_hangs_joins_the_parked_outcome(
    client, clean_database, hanging_upstream
):
    """A client that times out and retries mid-hang must not start a second call."""
    fixture = json.loads(FIXTURE.read_text())
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    permit = await create_tool_permit(
        client, wallet_id=wallet_id, key_id=provisioned["key_id"], tool_name=TOOL
    )
    request = _substitute(
        fixture["request"],
        {"<wallet_id>": wallet_id, "<permit_id>": permit["permit_id"]},
    )

    async def post() -> Any:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as caller:
            return await caller.post(
                "/mcp/messages", json=request, headers=provisioned["agent_headers"]
            )

    first_task = asyncio.create_task(post())
    while hanging_upstream.calls == 0:
        await asyncio.sleep(0.01)
    retry = await post()
    first = await first_task

    assert first.json()["error"]["message"] == "delivery_uncertain"
    assert retry.json() == first.json()
    assert hanging_upstream.calls == 1
    assert await _state(wallet_id, permit["permit_id"]) == PARKED
