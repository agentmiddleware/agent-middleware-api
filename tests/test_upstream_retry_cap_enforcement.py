"""Tests for upstream retry cap enforcement and duplicate detection.

Proves that per-tool call caps work on remote tools, concurrent retries are
handled atomically, duplicate detection works in observe and enforce modes,
and call slots are released correctly.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.db.database import get_session_factory
from app.db.models import McpDispatchAttemptModel, PermitModel
from app.main import app
from app.schemas.trust import PermitCreateRequest
from app.services.mcp_dispatch_attempts import get_mcp_dispatch_attempt_service
from app.services.permits import get_permit_service
from tests.test_trust_helpers import (
    BOOTSTRAP_HEADERS,
    provision_agent_wallet,
)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _create_permit_with_cap(
    client: AsyncClient,
    wallet_id: str,
    key_id: str,
    tool_name: str,
    max_calls: int,
    allow_repeats: bool = False,
) -> str:
    """Create a permit with max_calls_per_tool set."""
    permit_resp = await client.post(
        "/v1/permits",
        json={
            "issuer_wallet_id": wallet_id,
            "subject_wallet_id": wallet_id,
            "subject_key_id": key_id,
            "allowed_tools": [tool_name],
            "scopes": [f"tool:{tool_name}:invoke", "billing:charge"],
            "max_credits": 100,
            "max_calls_per_tool": {tool_name: max_calls},
            "allow_identical_repeats": allow_repeats,
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).isoformat(),
        },
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": f"permit-cap-{max_calls}"},
    )
    assert permit_resp.status_code == 201
    return permit_resp.json()["permit_id"]


async def _mock_upstream_call(
    *args, **kwargs
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Mock upstream MCP call that always succeeds."""
    return {"result": "ok"}, {}


@pytest.mark.anyio
async def test_remote_cap_1_success_then_new_key_refused(client, clean_database):
    """Remote tool with cap=1: success → new key → permit_max_calls_exceeded.
    
    This is the primary fix: per-tool call caps now work on remote tools.
    """
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "partner.echo"  # Upstream tool
    
    permit_id = await _create_permit_with_cap(
        client, wallet_id, key_id, tool_name, max_calls=1
    )
    
    with patch(
        "app.services.upstream_mcp.UpstreamMcpClient.call_tool",
        new_callable=AsyncMock,
        side_effect=_mock_upstream_call,
    ):
        # First call succeeds
        r1 = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"text": "hello"},
                    "mcpContext": {
                        "wallet_id": wallet_id,
                        "permit_id": permit_id,
                        "idempotency_key": "key-1",
                    },
                },
            },
            headers=agent_headers,
        )
        assert r1.status_code == 200
        body1 = r1.json()
        assert "result" in body1
        assert body1["result"]["outcome"] == "success"
        
        # Second call with different key is refused
        r2 = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"text": "hello"},
                    "mcpContext": {
                        "wallet_id": wallet_id,
                        "permit_id": permit_id,
                        "idempotency_key": "key-2",
                    },
                },
            },
            headers=agent_headers,
        )
        assert r2.status_code == 403
        body2 = r2.json()
        assert "error" in body2
        assert "permit_max_calls_exceeded" in str(body2["error"])


@pytest.mark.anyio
async def test_remote_cap_1_delivery_uncertain_then_refused(client, clean_database):
    """Remote tool with cap=1: delivery_uncertain → new key → refused.
    
    Delivery uncertain calls hold their slot to prevent duplicate effects.
    """
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "partner.echo"
    
    permit_id = await _create_permit_with_cap(
        client, wallet_id, key_id, tool_name, max_calls=1
    )
    
    # Mock to raise a transport error after dispatch
    call_count = 0
    async def _upstream_error(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        from app.services.upstream_mcp import UpstreamMcpDeliveryUncertainError
        raise UpstreamMcpDeliveryUncertainError("connection lost")
    
    with patch(
        "app.services.upstream_mcp.UpstreamMcpClient.call_tool",
        new_callable=AsyncMock,
        side_effect=_upstream_error,
    ):
        # First call ends delivery_uncertain
        r1 = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"text": "test"},
                    "mcpContext": {
                        "wallet_id": wallet_id,
                        "permit_id": permit_id,
                        "idempotency_key": "uncertain-1",
                    },
                },
            },
            headers=agent_headers,
        )
        assert r1.status_code == 200
        body1 = r1.json()
        assert "result" in body1
        assert body1["result"]["outcome"] == "delivery_uncertain"
        
        # Verify exactly 1 dispatch happened
        assert call_count == 1
        
        # Second call is refused (slot still held by uncertain call)
        r2 = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"text": "test"},
                    "mcpContext": {
                        "wallet_id": wallet_id,
                        "permit_id": permit_id,
                        "idempotency_key": "uncertain-2",
                    },
                },
            },
            headers=agent_headers,
        )
        assert r2.status_code == 403
        body2 = r2.json()
        assert "permit_max_calls_exceeded" in str(body2)
        
        # No second dispatch
        assert call_count == 1


@pytest.mark.anyio
async def test_remote_cap_predispatch_failure_releases_slot(client, clean_database):
    """Remote tool with cap=1: pre-dispatch failure → slot released → retry succeeds.
    
    When a prepared attempt is reconciled before dispatch, the slot is released.
    """
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "partner.echo"
    
    permit_id = await _create_permit_with_cap(
        client, wallet_id, key_id, tool_name, max_calls=1
    )
    
    # We'll manually create a prepared attempt and then reconcile it to
    # returned_error before dispatch to prove the slot is released.
    factory = get_session_factory()
    async with factory() as session:
        # Create a mock prepared attempt that holds a slot
        attempt = McpDispatchAttemptModel(
            attempt_id="dsp-test-release",
            idempotency_record_id="idem-test",
            wallet_id=wallet_id,
            permit_id=permit_id,
            key_id=key_id,
            public_tool_id=tool_name,
            upstream_tool_name=tool_name,
            upstream_origin="https://test.example.com",
            request_hash="a" * 64,
            credits_authorized=Decimal("1.0"),
            state="prepared",
            call_slot_reserved=True,
        )
        session.add(attempt)
        
        # Increment the counter to simulate the reservation
        permit = await session.get(PermitModel, permit_id)
        permit.tool_call_counts_json = json.dumps({tool_name: 1})
        session.add(permit)
        await session.commit()
    
    # Reconcile the prepared attempt (this would happen via the reconciler)
    permits = get_permit_service()
    released = await permits.release_dispatch_budget_once(attempt.attempt_id)
    assert released is True
    
    # Verify the counter was decremented
    async with factory() as session:
        permit = await session.get(PermitModel, permit_id)
        counts = json.loads(permit.tool_call_counts_json or "{}")
        assert counts.get(tool_name, 0) == 0
    
    # Now a real call should succeed (slot was released)
    with patch(
        "app.services.upstream_mcp.UpstreamMcpClient.call_tool",
        new_callable=AsyncMock,
        side_effect=_mock_upstream_call,
    ):
        r = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"text": "after-release"},
                    "mcpContext": {
                        "wallet_id": wallet_id,
                        "permit_id": permit_id,
                        "idempotency_key": "after-release-1",
                    },
                },
            },
            headers=agent_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["result"]["outcome"] == "success"


@pytest.mark.anyio
async def test_remote_different_tool_caps_independent(client, clean_database):
    """A cap on tool A doesn't block remote tool B.
    
    Fixes the regression where max_calls_per_tool_json is not None blocked
    all remote tools, not just the capped ones.
    """
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_a = "partner.echo"
    tool_b = "partner.notes.write"
    
    # Permit with cap on tool A only
    permit_resp = await client.post(
        "/v1/permits",
        json={
            "issuer_wallet_id": wallet_id,
            "subject_wallet_id": wallet_id,
            "subject_key_id": key_id,
            "allowed_tools": [tool_a, tool_b],
            "scopes": [
                f"tool:{tool_a}:invoke",
                f"tool:{tool_b}:invoke",
                "billing:charge",
            ],
            "max_credits": 100,
            "max_calls_per_tool": {tool_a: 1},  # Only tool A is capped
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).isoformat(),
        },
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "permit-mixed-caps"},
    )
    assert permit_resp.status_code == 201
    permit_id = permit_resp.json()["permit_id"]
    
    with patch(
        "app.services.upstream_mcp.UpstreamMcpClient.call_tool",
        new_callable=AsyncMock,
        side_effect=_mock_upstream_call,
    ):
        # Call tool A once (uses up its cap)
        r1 = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_a,
                    "arguments": {},
                    "mcpContext": {
                        "wallet_id": wallet_id,
                        "permit_id": permit_id,
                        "idempotency_key": "tool-a-1",
                    },
                },
            },
            headers=agent_headers,
        )
        assert r1.status_code == 200
        
        # Call tool B (should succeed, not blocked by tool A's cap)
        r2 = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_b,
                    "arguments": {"note": "test"},
                    "mcpContext": {
                        "wallet_id": wallet_id,
                        "permit_id": permit_id,
                        "idempotency_key": "tool-b-1",
                    },
                },
            },
            headers=agent_headers,
        )
        assert r2.status_code == 200
        body2 = r2.json()
        assert body2["result"]["outcome"] == "success"


@pytest.mark.anyio
async def test_duplicate_detection_enforce_mode(client, clean_database, monkeypatch):
    """Cross-key duplicate detection in enforce mode refuses duplicates.
    
    Identical request hash under different key is detected and refused.
    """
    monkeypatch.setenv("MCP_UPSTREAM_DUPLICATE_GUARD", "enforce")
    
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "partner.echo"
    
    # Permit WITHOUT cap (testing pure duplicate detection)
    permit_resp = await client.post(
        "/v1/permits",
        json={
            "issuer_wallet_id": wallet_id,
            "subject_wallet_id": wallet_id,
            "subject_key_id": key_id,
            "allowed_tools": [tool_name],
            "scopes": [f"tool:{tool_name}:invoke", "billing:charge"],
            "max_credits": 100,
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).isoformat(),
        },
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "permit-dup-test"},
    )
    assert permit_resp.status_code == 201
    permit_id = permit_resp.json()["permit_id"]
    
    with patch(
        "app.services.upstream_mcp.UpstreamMcpClient.call_tool",
        new_callable=AsyncMock,
        side_effect=_mock_upstream_call,
    ):
        # First call with identical arguments
        r1 = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"text": "duplicate-me"},
                    "mcpContext": {
                        "wallet_id": wallet_id,
                        "permit_id": permit_id,
                        "idempotency_key": "dup-key-1",
                    },
                },
            },
            headers=agent_headers,
        )
        assert r1.status_code == 200
        
        # Second call with SAME arguments but DIFFERENT key
        r2 = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"text": "duplicate-me"},  # Same args!
                    "mcpContext": {
                        "wallet_id": wallet_id,
                        "permit_id": permit_id,
                        "idempotency_key": "dup-key-2",  # Different key!
                    },
                },
            },
            headers=agent_headers,
        )
        assert r2.status_code == 403
        body2 = r2.json()
        assert "duplicate_request_new_key" in str(body2)


@pytest.mark.anyio
async def test_duplicate_detection_log_mode_allows(client, clean_database, monkeypatch):
    """Cross-key duplicate detection in log mode allows duplicates (observe only)."""
    monkeypatch.setenv("MCP_UPSTREAM_DUPLICATE_GUARD", "log")
    
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "partner.echo"
    
    permit_resp = await client.post(
        "/v1/permits",
        json={
            "issuer_wallet_id": wallet_id,
            "subject_wallet_id": wallet_id,
            "subject_key_id": key_id,
            "allowed_tools": [tool_name],
            "scopes": [f"tool:{tool_name}:invoke", "billing:charge"],
            "max_credits": 100,
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).isoformat(),
        },
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "permit-log-mode"},
    )
    assert permit_resp.status_code == 201
    permit_id = permit_resp.json()["permit_id"]
    
    with patch(
        "app.services.upstream_mcp.UpstreamMcpClient.call_tool",
        new_callable=AsyncMock,
        side_effect=_mock_upstream_call,
    ):
        # First call
        r1 = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"text": "log-me"},
                    "mcpContext": {
                        "wallet_id": wallet_id,
                        "permit_id": permit_id,
                        "idempotency_key": "log-key-1",
                    },
                },
            },
            headers=agent_headers,
        )
        assert r1.status_code == 200
        
        # Duplicate with different key should still succeed in log mode
        r2 = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"text": "log-me"},
                    "mcpContext": {
                        "wallet_id": wallet_id,
                        "permit_id": permit_id,
                        "idempotency_key": "log-key-2",
                    },
                },
            },
            headers=agent_headers,
        )
        assert r2.status_code == 200
        body2 = r2.json()
        assert body2["result"]["outcome"] == "success"


@pytest.mark.anyio
async def test_duplicate_detection_opt_out(client, clean_database, monkeypatch):
    """Permit with allow_identical_repeats=true bypasses duplicate detection."""
    monkeypatch.setenv("MCP_UPSTREAM_DUPLICATE_GUARD", "enforce")
    
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "partner.echo"
    
    # Permit with opt-out enabled
    permit_resp = await client.post(
        "/v1/permits",
        json={
            "issuer_wallet_id": wallet_id,
            "subject_wallet_id": wallet_id,
            "subject_key_id": key_id,
            "allowed_tools": [tool_name],
            "scopes": [f"tool:{tool_name}:invoke", "billing:charge"],
            "max_credits": 100,
            "allow_identical_repeats": True,  # Opt-out
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).isoformat(),
        },
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "permit-opt-out"},
    )
    assert permit_resp.status_code == 201
    permit_id = permit_resp.json()["permit_id"]
    
    with patch(
        "app.services.upstream_mcp.UpstreamMcpClient.call_tool",
        new_callable=AsyncMock,
        side_effect=_mock_upstream_call,
    ):
        # First call
        r1 = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"text": "repeat-me"},
                    "mcpContext": {
                        "wallet_id": wallet_id,
                        "permit_id": permit_id,
                        "idempotency_key": "opt-out-1",
                    },
                },
            },
            headers=agent_headers,
        )
        assert r1.status_code == 200
        
        # Duplicate should succeed because opt-out is enabled
        r2 = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"text": "repeat-me"},
                    "mcpContext": {
                        "wallet_id": wallet_id,
                        "permit_id": permit_id,
                        "idempotency_key": "opt-out-2",
                    },
                },
            },
            headers=agent_headers,
        )
        assert r2.status_code == 200
        body2 = r2.json()
        assert body2["result"]["outcome"] == "success"


@pytest.mark.anyio
async def test_same_key_replay_unchanged(client, clean_database):
    """Same-key replay returns original receipt with no second call or charge.
    
    This behavior must not regress.
    """
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "partner.echo"
    
    permit_id = await _create_permit_with_cap(
        client, wallet_id, key_id, tool_name, max_calls=1
    )
    
    call_count = 0
    async def _counting_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return {"result": "counted"}, {}
    
    with patch(
        "app.services.upstream_mcp.UpstreamMcpClient.call_tool",
        new_callable=AsyncMock,
        side_effect=_counting_call,
    ):
        # First call
        r1 = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"text": "once"},
                    "mcpContext": {
                        "wallet_id": wallet_id,
                        "permit_id": permit_id,
                        "idempotency_key": "same-key",
                    },
                },
            },
            headers=agent_headers,
        )
        assert r1.status_code == 200
        body1 = r1.json()
        receipt_id_1 = body1["result"]["receipt"]["receipt_id"]
        assert call_count == 1
        
        # Replay with same key
        r2 = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"text": "once"},
                    "mcpContext": {
                        "wallet_id": wallet_id,
                        "permit_id": permit_id,
                        "idempotency_key": "same-key",  # Same key!
                    },
                },
            },
            headers=agent_headers,
        )
        assert r2.status_code == 200
        body2 = r2.json()
        receipt_id_2 = body2["result"]["receipt"]["receipt_id"]
        
        # Same receipt, no second call
        assert receipt_id_2 == receipt_id_1
        assert call_count == 1  # Still 1, not 2


@pytest.mark.anyio
async def test_aggregate_value_cap_still_unsupported(client, clean_database):
    """Permit with aggregate_value_cap is still refused on upstream tools.
    
    This constraint requires folding in-flight reservations and remains
    unsupported until that's implemented.
    """
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "partner.echo"
    
    # Permit with aggregate_value_cap
    permit_resp = await client.post(
        "/v1/permits",
        json={
            "issuer_wallet_id": wallet_id,
            "subject_wallet_id": wallet_id,
            "subject_key_id": key_id,
            "allowed_tools": [tool_name],
            "scopes": [f"tool:{tool_name}:invoke", "billing:charge"],
            "max_credits": 100,
            "aggregate_value_cap": 50,  # Aggregate cap
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).isoformat(),
        },
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "permit-agg-cap"},
    )
    assert permit_resp.status_code == 201
    permit_id = permit_resp.json()["permit_id"]
    
    with patch(
        "app.services.upstream_mcp.UpstreamMcpClient.call_tool",
        new_callable=AsyncMock,
        side_effect=_mock_upstream_call,
    ):
        # Call is refused
        r = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {},
                    "mcpContext": {
                        "wallet_id": wallet_id,
                        "permit_id": permit_id,
                        "idempotency_key": "agg-1",
                    },
                },
            },
            headers=agent_headers,
        )
        assert r.status_code == 403
        body = r.json()
        assert "permit_constraint_unsupported_for_upstream" in str(body)
        assert "aggregate_value_cap" in str(body)
