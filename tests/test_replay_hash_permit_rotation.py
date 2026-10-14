"""The governed replay hash binds the logical call, not the permit that paid.

Hash identity is (tool, arguments, wallet, calling key). The permit stays on
the receipt as provenance. A permit renewed or rotated while a call is in
flight must therefore not turn the caller's legitimate same-key retry into
``idempotency_key_reused``; the retry replays the original receipt, which
still names the original permit. Negative paths: changed arguments still
conflict, and a second API key on the same wallet cannot reach another key's
result by presenting its own permit.

Also covers the stale lease: a crash right after the key insert (before the
atomic prepare) must not leave the key in progress forever.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import IdempotencyRecordModel, LedgerEntryModel
from app.main import app
from app.services.idempotency import (
    GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
    IdempotencyInProgressError,
    get_idempotency_service,
)
from app.services.mcp_dispatch_attempts import McpDispatchAttemptService
from app.services.service_registry import get_service_registry
from app.services.signing_keys import sha256_hex
from tests.test_idempotency_mismatched_body_race import BlockingExecutor
from tests.test_mcp_upstream_governed import (
    FakeUpstreamExecutor,
    _call_body,
    _register_upstream,
)
from tests.test_trust_helpers import (
    BOOTSTRAP_HEADERS,
    create_tool_permit,
    provision_agent_wallet,
)

pytestmark = pytest.mark.anyio

CONFLICT = {"code": -32009, "message": "idempotency_key_reused"}


def _conflict_head(err):
    """-32009 now carries request hashes in data (item 1); compare code/message."""
    if not isinstance(err, dict):
        return err
    return {k: err.get(k) for k in ("code", "message")}


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as caller:
        yield caller


async def _post(body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as caller:
        response = await caller.post("/mcp/messages", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _debits(wallet_id: str) -> int:
    async with get_session_factory()() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(LedgerEntryModel)
                .where(
                    LedgerEntryModel.wallet_id == wallet_id,
                    LedgerEntryModel.action == "debit",
                )
            )
            or 0
        )


async def _two_permits(client, tool: str, executor: FakeUpstreamExecutor):
    provisioned = await provision_agent_wallet(client)
    _register_upstream(tool, executor)
    permits = [
        await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name=tool,
            idem_key=f"{tool}-permit-{index}",
        )
        for index in range(2)
    ]
    assert permits[0]["permit_id"] != permits[1]["permit_id"]
    return provisioned, permits


def _body(tool, provisioned, permit, key="rotate-key", message="hello"):
    return _call_body(
        tool_name=tool,
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        idempotency_key=key,
        message=message,
    )


async def test_retry_with_renewed_permit_replays_original_receipt(
    client, clean_database
):
    tool = "rotate-done"
    executor = FakeUpstreamExecutor("success")
    provisioned, (old, new) = await _two_permits(client, tool, executor)
    headers = provisioned["agent_headers"]
    try:
        first = await _post(_body(tool, provisioned, old), headers)
        assert "result" in first, first
        retry = await _post(_body(tool, provisioned, new), headers)

        assert retry.get("error") is None, retry
        assert retry["result"] == first["result"]
        # Provenance: the receipt still names the permit that authorized it.
        assert retry["result"]["receipt"]["permit_id"] == old["permit_id"]
        assert executor.dispatch_count == 1
        assert await _debits(provisioned["agent_wallet_id"]) == 1
    finally:
        get_service_registry().unregister_local(tool)


async def test_permit_rotated_mid_flight_retry_joins_original(client, clean_database):
    tool = "rotate-live"
    executor = BlockingExecutor("success")
    provisioned, (old, new) = await _two_permits(client, tool, executor)
    headers = provisioned["agent_headers"]
    try:
        original = asyncio.create_task(_post(_body(tool, provisioned, old), headers))
        await asyncio.wait_for(executor.entered.wait(), timeout=10)
        retry = asyncio.create_task(_post(_body(tool, provisioned, new), headers))
        await asyncio.sleep(0.2)
        executor.release.set()
        first, second = await asyncio.wait_for(
            asyncio.gather(original, retry), timeout=30
        )

        assert "result" in first, first
        assert second.get("result") == first["result"], second
        assert first["result"]["receipt"]["permit_id"] == old["permit_id"]
        assert executor.dispatch_count == 1
        assert await _debits(provisioned["agent_wallet_id"]) == 1
    finally:
        executor.release.set()
        get_service_registry().unregister_local(tool)


async def test_renewed_permit_with_changed_arguments_still_conflicts(
    client, clean_database
):
    tool = "rotate-changed"
    executor = FakeUpstreamExecutor("success")
    provisioned, (old, new) = await _two_permits(client, tool, executor)
    headers = provisioned["agent_headers"]
    try:
        assert "result" in await _post(_body(tool, provisioned, old), headers)
        changed = await _post(_body(tool, provisioned, new, message="other"), headers)
        assert _conflict_head(changed["error"]) == CONFLICT
        assert executor.dispatch_count == 1
        assert await _debits(provisioned["agent_wallet_id"]) == 1
    finally:
        get_service_registry().unregister_local(tool)


async def test_second_key_on_same_wallet_cannot_replay_through_own_permit(
    client, clean_database
):
    """Dropping permit_id must not let a sibling key read another key's result."""
    tool = "rotate-sibling"
    executor = FakeUpstreamExecutor("success")
    provisioned, (old, _) = await _two_permits(client, tool, executor)
    wallet_id = provisioned["agent_wallet_id"]
    try:
        first = await _post(_body(tool, provisioned, old), provisioned["agent_headers"])
        assert "result" in first, first

        sibling = await client.post(
            "/v1/api-keys",
            json={"wallet_id": wallet_id, "key_name": "sibling", "expires_in_days": 1},
            headers=BOOTSTRAP_HEADERS,
        )
        assert sibling.status_code == 201, sibling.text
        sibling_permit = await create_tool_permit(
            client,
            wallet_id=wallet_id,
            key_id=sibling.json()["key_id"],
            tool_name=tool,
            idem_key="rotate-sibling-permit",
        )
        stolen = await _post(
            _body(tool, provisioned, sibling_permit),
            {"X-API-Key": sibling.json()["api_key"]},
        )
        assert "result" not in stolen, stolen
        assert _conflict_head(stolen["error"]) == CONFLICT
        assert executor.dispatch_count == 1
        assert await _debits(wallet_id) == 1
    finally:
        get_service_registry().unregister_local(tool)


async def test_pre_upgrade_permit_bound_record_still_replays(client, clean_database):
    """Rows hashed before this change (permit_id included) keep replaying."""
    tool = "rotate-legacy"
    executor = FakeUpstreamExecutor("success")
    provisioned, (old, new) = await _two_permits(client, tool, executor)
    headers = provisioned["agent_headers"]
    wallet_id = provisioned["agent_wallet_id"]
    try:
        first = await _post(_body(tool, provisioned, old), headers)
        assert "result" in first, first
        legacy_hash = sha256_hex(
            {
                "tool_name": tool,
                "arguments": {"message": "hello"},
                "wallet_id": wallet_id,
                "permit_id": old["permit_id"],
            }
        )
        async with get_session_factory()() as session:
            record = (
                await session.execute(
                    select(IdempotencyRecordModel).where(
                        IdempotencyRecordModel.wallet_id == wallet_id,
                        IdempotencyRecordModel.endpoint
                        == GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
                    )
                )
            ).scalar_one()
            assert record.request_hash != legacy_hash
            record.request_hash = legacy_hash
            await session.commit()

        assert (await _post(_body(tool, provisioned, old), headers)) == first
        # A legacy row can only be matched by the permit it was hashed with.
        rotated = await _post(_body(tool, provisioned, new), headers)
        assert _conflict_head(rotated["error"]) == CONFLICT
        assert executor.dispatch_count == 1
        assert await _debits(wallet_id) == 1
    finally:
        get_service_registry().unregister_local(tool)


class _ProcessDied(BaseException):
    """Stands in for a crash: not an Exception, so no handler cleans up."""


async def test_crash_after_key_insert_lease_is_released_by_sweep(
    client, clean_database, monkeypatch
):
    tool = "stale-lease"
    executor = FakeUpstreamExecutor("success")
    provisioned, (permit, _) = await _two_permits(client, tool, executor)
    headers = provisioned["agent_headers"]
    wallet_id = provisioned["agent_wallet_id"]
    body = _body(tool, provisioned, permit, key="stale-lease-key")
    idem = get_idempotency_service()
    try:

        async def die(*_args: Any, **_kwargs: Any) -> Any:
            raise _ProcessDied()

        with monkeypatch.context() as patch:
            patch.setattr(
                McpDispatchAttemptService, "authorize_reserve_and_prepare", die
            )
            # Starlette middleware may wrap it in a BaseExceptionGroup.
            with pytest.raises(BaseException):
                await client.post("/mcp/messages", json=body, headers=headers)

        record = await idem.get_record(
            wallet_id=wallet_id,
            endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
            idempotency_key="stale-lease-key",
        )
        assert record is not None and record.response_json is None
        assert record.operation_kind == "upstream_mcp"
        payload = {
            "tool_name": tool,
            "arguments": {"message": "hello"},
            "wallet_id": wallet_id,
            "key_id": provisioned["key_id"],
        }
        assert record.request_hash == sha256_hex(payload)
        # While the lease is young it is honoured: retries see in-progress.
        with pytest.raises(IdempotencyInProgressError):
            await idem.begin_with_record(
                wallet_id=wallet_id,
                endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
                idempotency_key="stale-lease-key",
                request_payload=payload,
            )
        assert await idem.reconcile_stuck_records(idle_seconds=300) == (0, 0)

        async with get_session_factory()() as session:
            stored = await session.get(IdempotencyRecordModel, record.record_id)
            assert stored is not None
            stored.created_at = utc_now() - timedelta(minutes=10)
            await session.commit()
        # The production sweep window (app/main.py periodic_cleanup).
        assert await idem.reconcile_stuck_records(idle_seconds=300) == (1, 0)

        retried = await _post(body, headers)
        assert "result" in retried, retried
        assert Decimal(retried["result"]["receipt"]["credits_charged"]) == 2
        assert executor.dispatch_count == 1
        assert await _debits(wallet_id) == 1
        assert (await _post(body, headers)) == retried
        assert (
            json.loads(
                (
                    await idem.get_record(
                        wallet_id=wallet_id,
                        endpoint=GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
                        idempotency_key="stale-lease-key",
                    )
                ).response_json
            )["receipt"]["receipt_id"]
            == retried["result"]["receipt"]["receipt_id"]
        )
    finally:
        get_service_registry().unregister_local(tool)
