"""PostgreSQL concurrency proof for duplicate guard enforcement.

Parallel identical new-key calls should produce exactly one dispatch, one charge,
and N-1 duplicate_request_new_key denials under enforce mode.
"""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import DuplicateGuardMode
from app.core.time import utc_now
from app.db.database import get_engine, get_session_factory
from app.db.models import LedgerEntryModel, McpDispatchAttemptModel, ReceiptModel
from app.main import app
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import (
    BOOTSTRAP_HEADERS,
    provision_agent_wallet,
)


def _require_opted_in_postgres() -> None:
    """Skip test if not running against PostgreSQL with opt-in flag."""
    engine = get_engine()
    if engine is None or engine.dialect.name != "postgresql":
        pytest.skip("requires a PostgreSQL DATABASE_URL for real row-lock semantics")
    if os.environ.get("RUN_POSTGRES_CONCURRENCY_TESTS") != "1":
        pytest.skip(
            "set RUN_POSTGRES_CONCURRENCY_TESTS=1 only with an isolated "
            "PostgreSQL database"
        )


class FakeUpstreamExecutor:
    """Fake upstream tool that tracks dispatch count."""

    def __init__(self):
        self.dispatch_count = 0
        self.calls = []

    async def call_tool(self, arguments, *, invocation_id, idempotency_key, before_dispatch):
        await before_dispatch()
        self.dispatch_count += 1
        self.calls.append({
            "arguments": arguments,
            "invocation_id": invocation_id,
            "idempotency_key": idempotency_key,
        })
        return {
            "content": [{"type": "text", "text": "success"}],
            "isError": False,
        }


def _register_upstream(tool_name: str, executor: FakeUpstreamExecutor):
    """Register a fake upstream tool."""
    from app.services.upstream_mcp import UpstreamMcpAdapter
    adapter = UpstreamMcpAdapter(
        base_url="https://fake.example.com",
        bearer_token="fake-token",
        tool_name=tool_name,
        public_tool_id=tool_name,
        credits_per_call=Decimal("10.0"),
        connect_timeout_seconds=5.0,
        call_timeout_seconds=30.0,
        max_response_bytes=1_048_576,
    )
    adapter._executor = executor
    get_service_registry().register_upstream(tool_name, adapter)


def _call_body(*, tool_name, wallet_id, permit_id, idempotency_key, message):
    """Build an /mcp/messages call body."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {"message": message},
            "_meta": {
                "progressToken": 123,
                "walletId": wallet_id,
                "permitId": permit_id,
                "idempotencyKey": idempotency_key,
            },
        },
    }


@pytest.mark.anyio
async def test_parallel_identical_new_keys_enforce_mode_one_dispatch(monkeypatch):
    """N concurrent identical new-key calls produce 1 dispatch, 1 charge, N-1 denials.
    
    PostgreSQL concurrency proof: under enforce mode, concurrent calls with
    different idempotency keys but identical arguments produce exactly one
    upstream dispatch and exactly one ledger debit. The permit row lock and
    duplicate detection query serialize access.
    """
    _require_opted_in_postgres()
    
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "MCP_UPSTREAM_DUPLICATE_GUARD", DuplicateGuardMode.ENFORCE)
    
    factory = get_session_factory()
    # Provision agent
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        provisioned = await provision_agent_wallet(client)
        wallet_id = provisioned["agent_wallet_id"]
        key_id = provisioned["key_id"]
        agent_headers = provisioned["agent_headers"]
        
        tool_name = "test.concurrent.dup"
        executor = FakeUpstreamExecutor()
        _register_upstream(tool_name, executor)
        
        try:
            # Create permit
            permit_resp = await client.post(
                "/v1/permits",
                json={
                    "issuer_wallet_id": wallet_id,
                    "subject_wallet_id": wallet_id,
                    "subject_key_id": key_id,
                    "allowed_tools": [tool_name],
                    "scopes": [f"tool:{tool_name}:invoke", "billing:charge"],
                    "max_credits": 1000,
                    "expires_at": (utc_now() + timedelta(hours=1)).isoformat(),
                },
                headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "permit-concurrent-dup"},
            )
            assert permit_resp.status_code == 201
            permit_id = permit_resp.json()["permit_id"]
            
            # Launch N parallel calls with DIFFERENT keys but IDENTICAL arguments
            N = 5
            identical_message = "duplicate-me-parallel"
            
            async def make_call(idx: int):
                return await client.post(
                    "/mcp/messages",
                    json=_call_body(
                        tool_name=tool_name,
                        wallet_id=wallet_id,
                        permit_id=permit_id,
                        idempotency_key=f"parallel-dup-key-{idx}",
                        message=identical_message,
                    ),
                    headers=agent_headers,
                )
            
            # Fire all calls simultaneously
            responses = await asyncio.gather(*[make_call(i) for i in range(N)])
            
            # All should return 200
            for r in responses:
                assert r.status_code == 200
            
            # Count successes vs denials
            success_count = 0
            denial_count = 0
            for r in responses:
                body = r.json()
                if "error" in body:
                    assert body["error"]["message"] == "duplicate_request_new_key"
                    denial_count += 1
                else:
                    assert body["result"]["receipt"]["outcome"] == "success"
                    success_count += 1
            
            # Exactly one success, N-1 denials
            assert success_count == 1, f"Expected 1 success, got {success_count}"
            assert denial_count == N - 1, f"Expected {N-1} denials, got {denial_count}"
            
            # Exactly one dispatch
            assert executor.dispatch_count == 1
            
            # Verify database state: 1 debit, N receipts (1 success + N-1 denials)
            async with factory() as session:
                debits = (
                    await session.execute(
                        select(LedgerEntryModel).where(
                            LedgerEntryModel.wallet_id == wallet_id,
                            LedgerEntryModel.entry_type == "debit",
                        )
                    )
                ).scalars().all()
                # Should have exactly one debit for the successful dispatch
                debit_count = len([d for d in debits if d.amount > 0])
                assert debit_count == 1, f"Expected 1 debit, found {debit_count}"
                
                receipts = (
                    await session.execute(
                        select(ReceiptModel).where(
                            ReceiptModel.permit_id == permit_id
                        )
                    )
                ).scalars().all()
                assert len(receipts) == N
                
                # One success receipt, N-1 denial receipts
                success_receipts = [r for r in receipts if r.outcome == "success"]
                denial_receipts = [r for r in receipts if r.outcome == "denied"]
                assert len(success_receipts) == 1
                assert len(denial_receipts) == N - 1
                
                # All denial receipts have reason_code duplicate_request_new_key
                for dr in denial_receipts:
                    assert dr.reason_code == "duplicate_request_new_key"
                
                # Verify dispatch attempts: exactly 1 should have dispatched
                attempts = (
                    await session.execute(
                        select(McpDispatchAttemptModel).where(
                            McpDispatchAttemptModel.permit_id == permit_id
                        )
                    )
                ).scalars().all()
                dispatched_attempts = [a for a in attempts if a.dispatched_at is not None]
                assert len(dispatched_attempts) == 1
                
        finally:
            get_service_registry().unregister_local(tool_name)


@pytest.mark.asyncio(loop_scope="session")
async def test_duplicate_guard_respects_permit_window_override(monkeypatch):
    """Permit repeat_window_seconds overrides global default."""
    _require_opted_in_postgres()
    
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "MCP_UPSTREAM_DUPLICATE_GUARD", DuplicateGuardMode.ENFORCE)
    # Set a very long global window
    monkeypatch.setattr(settings, "MCP_UPSTREAM_DUPLICATE_WINDOW_SECONDS", 86400)
    
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        provisioned = await provision_agent_wallet(client)
        wallet_id = provisioned["agent_wallet_id"]
        key_id = provisioned["key_id"]
        agent_headers = provisioned["agent_headers"]
        
        tool_name = "test.window.override"
        executor = FakeUpstreamExecutor()
        _register_upstream(tool_name, executor)
        
        try:
            # Create permit with a SHORT window (1 second)
            permit_resp = await client.post(
                "/v1/permits",
                json={
                    "issuer_wallet_id": wallet_id,
                    "subject_wallet_id": wallet_id,
                    "subject_key_id": key_id,
                    "allowed_tools": [tool_name],
                    "scopes": [f"tool:{tool_name}:invoke", "billing:charge"],
                    "max_credits": 1000,
                    "expires_at": (utc_now() + timedelta(hours=1)).isoformat(),
                    "repeat_window_seconds": 1,  # Very short window
                },
                headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "permit-window-test"},
            )
            assert permit_resp.status_code == 201
            permit_id = permit_resp.json()["permit_id"]
            permit_data = permit_resp.json()
            assert permit_data["repeat_window_seconds"] == 1
            
            # First call
            r1 = await client.post(
                "/mcp/messages",
                json=_call_body(
                    tool_name=tool_name,
                    wallet_id=wallet_id,
                    permit_id=permit_id,
                    idempotency_key="window-key-1",
                    message="window-test",
                ),
                headers=agent_headers,
            )
            assert r1.status_code == 200
            assert r1.json()["result"]["receipt"]["outcome"] == "success"
            
            # Immediate second call with new key, identical args - should be blocked
            r2 = await client.post(
                "/mcp/messages",
                json=_call_body(
                    tool_name=tool_name,
                    wallet_id=wallet_id,
                    permit_id=permit_id,
                    idempotency_key="window-key-2",
                    message="window-test",
                ),
                headers=agent_headers,
            )
            assert r2.status_code == 200
            assert "error" in r2.json()
            assert r2.json()["error"]["message"] == "duplicate_request_new_key"
            
            # Wait for window to expire
            await asyncio.sleep(1.5)
            
            # Third call with new key after window - should succeed
            r3 = await client.post(
                "/mcp/messages",
                json=_call_body(
                    tool_name=tool_name,
                    wallet_id=wallet_id,
                    permit_id=permit_id,
                    idempotency_key="window-key-3",
                    message="window-test",
                ),
                headers=agent_headers,
            )
            assert r3.status_code == 200
            assert r3.json()["result"]["receipt"]["outcome"] == "success"
            
            # Should have 2 dispatches (first + after window expiry)
            assert executor.dispatch_count == 2
            
        finally:
            get_service_registry().unregister_local(tool_name)


@pytest.mark.asyncio(loop_scope="session")
async def test_duplicate_guard_off_mode_allows_duplicates(monkeypatch):
    """OFF mode disables duplicate detection entirely."""
    _require_opted_in_postgres()
    
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "MCP_UPSTREAM_DUPLICATE_GUARD", DuplicateGuardMode.OFF)
    
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        provisioned = await provision_agent_wallet(client)
        wallet_id = provisioned["agent_wallet_id"]
        key_id = provisioned["key_id"]
        agent_headers = provisioned["agent_headers"]
        
        tool_name = "test.off.mode"
        executor = FakeUpstreamExecutor()
        _register_upstream(tool_name, executor)
        
        try:
            permit_resp = await client.post(
                "/v1/permits",
                json={
                    "issuer_wallet_id": wallet_id,
                    "subject_wallet_id": wallet_id,
                    "subject_key_id": key_id,
                    "allowed_tools": [tool_name],
                    "scopes": [f"tool:{tool_name}:invoke", "billing:charge"],
                    "max_credits": 1000,
                    "expires_at": (utc_now() + timedelta(hours=1)).isoformat(),
                },
                headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "permit-off-mode"},
            )
            assert permit_resp.status_code == 201
            permit_id = permit_resp.json()["permit_id"]
            
            # Fire 3 identical calls with different keys
            for i in range(3):
                r = await client.post(
                    "/mcp/messages",
                    json=_call_body(
                        tool_name=tool_name,
                        wallet_id=wallet_id,
                        permit_id=permit_id,
                        idempotency_key=f"off-key-{i}",
                        message="identical",
                    ),
                    headers=agent_headers,
                )
                assert r.status_code == 200
                # All should succeed in OFF mode
                assert r.json()["result"]["receipt"]["outcome"] == "success"
            
            # All 3 dispatched
            assert executor.dispatch_count == 3
            
        finally:
            get_service_registry().unregister_local(tool_name)
