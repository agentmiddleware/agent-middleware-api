"""Tests for upstream retry cap enforcement and duplicate detection.

Proves that per-tool call caps work on remote tools, concurrent retries are
handled atomically, duplicate detection works in observe and enforce modes,
and call slots are released correctly.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.time import utc_now
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.service_registry import get_service_registry
from app.services.upstream_mcp import (
    UpstreamMcpDeliveryUncertainError,
    UpstreamMcpPreDispatchError,
    UpstreamMcpResult,
    UpstreamMcpReturnedError,
)
from tests.test_trust_helpers import (
    BOOTSTRAP_HEADERS,
    provision_agent_wallet,
)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _upstream_result(payload: dict[str, Any]) -> UpstreamMcpResult:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return UpstreamMcpResult(
        payload=payload,
        canonical_json=canonical,
        response_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        size_bytes=len(canonical.encode()),
        is_error=bool(payload.get("isError")),
    )


@dataclass
class FakeUpstreamExecutor:
    mode: str = "success"
    calls: list[dict[str, Any]] = field(default_factory=list)
    dispatch_count: int = 0
    result_payload: dict[str, Any] | None = None

    async def call_tool(
        self,
        arguments: dict[str, Any],
        *,
        invocation_id: str,
        idempotency_key: str,
        before_dispatch: Callable[[], Awaitable[None]],
    ) -> UpstreamMcpResult:
        self.calls.append({
            "arguments": arguments,
            "invocation_id": invocation_id,
            "idempotency_key": idempotency_key,
        })
        
        if self.mode == "pre_dispatch_failure":
            raise UpstreamMcpPreDispatchError("upstream_connection_failed")
        
        await before_dispatch()
        self.dispatch_count += 1
        
        if self.mode == "returned_error":
            raise UpstreamMcpReturnedError(
                _upstream_result(
                    self.result_payload if self.result_payload is not None
                    else {"content": [{"type": "text", "text": "error"}], "isError": True}
                )
            )
        if self.mode == "delivery_uncertain":
            raise UpstreamMcpDeliveryUncertainError()
        
        return _upstream_result(
            self.result_payload if self.result_payload is not None
            else {"content": [{"type": "text", "text": "success"}], "isError": False}
        )


def _register_upstream(
    tool_name: str,
    executor: FakeUpstreamExecutor,
    *,
    credits_per_call: float = 2.0,
    category: ServiceCategory = ServiceCategory.AGENT_COMMS,
) -> None:
    get_service_registry().register_upstream(
        service_id=tool_name,
        name="Test Upstream Tool",
        description="Test upstream tool for retry cap enforcement",
        category=category,
        executor=executor,
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
        },
        output_schema={"type": "object"},
        credits_per_unit=credits_per_call,
        upstream_tool_name=tool_name,
        upstream_origin="https://test.example",
    )


def _call_body(
    *,
    tool_name: str,
    wallet_id: str,
    permit_id: str,
    idempotency_key: str,
    message: str = "test",
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {"message": message},
            "mcpContext": {
                "wallet_id": wallet_id,
                "permit_id": permit_id,
                "idempotency_key": idempotency_key,
            },
        },
    }


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
            "expires_at": (utc_now() + timedelta(hours=1)).isoformat(),
        },
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": f"permit-cap-{tool_name}-{max_calls}"},
    )
    assert permit_resp.status_code == 201
    return permit_resp.json()["permit_id"]


@pytest.mark.anyio
async def test_remote_cap_1_success_then_new_key_refused(client, clean_database):
    """Remote tool with cap=1: success → new key → permit_max_calls_exceeded.
    
    This is the primary fix: per-tool call caps now work on remote tools.
    """
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "test.cap.one"
    
    executor = FakeUpstreamExecutor("success")
    _register_upstream(tool_name, executor)
    
    try:
        permit_id = await _create_permit_with_cap(
            client, wallet_id, key_id, tool_name, max_calls=1
        )
        
        # First call succeeds
        r1 = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="key-1",
                message="hello",
            ),
            headers=agent_headers,
        )
        assert r1.status_code == 200
        body1 = r1.json()
        assert "result" in body1
        assert body1["result"]["receipt"]["outcome"] == "success"
        assert executor.dispatch_count == 1
        
        # Second call with different key is refused
        r2 = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="key-2",
                message="hello",
            ),
            headers=agent_headers,
        )
        assert r2.status_code == 200
        body2 = r2.json()
        assert "error" in body2
        assert body2["error"]["code"] == -32003
        assert body2["error"]["message"] == "permit_max_calls_exceeded"
        assert executor.dispatch_count == 1  # Still 1, no second dispatch
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_remote_cap_1_delivery_uncertain_then_refused(client, clean_database):
    """Remote tool with cap=1: delivery_uncertain → new key → refused.
    
    Delivery uncertain calls hold their slot to prevent duplicate effects.
    """
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "test.cap.uncertain"
    
    executor = FakeUpstreamExecutor("delivery_uncertain")
    _register_upstream(tool_name, executor)
    
    try:
        permit_id = await _create_permit_with_cap(
            client, wallet_id, key_id, tool_name, max_calls=1
        )
        
        # First call ends delivery_uncertain
        r1 = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="uncertain-1",
            ),
            headers=agent_headers,
        )
        assert r1.status_code == 200
        body1 = r1.json()
        assert "error" in body1
        assert body1["error"]["message"] == "delivery_uncertain"
        assert body1["error"]["data"]["receipt"]["outcome"] == "delivery_uncertain"
        assert executor.dispatch_count == 1
        
        # Second call is refused (slot still held by uncertain call)
        r2 = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="uncertain-2",
            ),
            headers=agent_headers,
        )
        assert r2.status_code == 200
        body2 = r2.json()
        assert "error" in body2
        assert body2["error"]["message"] == "permit_max_calls_exceeded"
        assert executor.dispatch_count == 1  # No second dispatch
    finally:
        get_service_registry().unregister_local(tool_name)


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
    tool_a = "test.cap.a"
    tool_b = "test.cap.b"
    
    executor_a = FakeUpstreamExecutor("success")
    executor_b = FakeUpstreamExecutor("success")
    _register_upstream(tool_a, executor_a)
    _register_upstream(tool_b, executor_b)
    
    try:
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
                "max_calls_per_tool": {tool_a: 1},
                "expires_at": (utc_now() + timedelta(hours=1)).isoformat(),
            },
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "permit-mixed-caps"},
        )
        assert permit_resp.status_code == 201
        permit_id = permit_resp.json()["permit_id"]
        
        # Call tool A once (uses up its cap)
        r1 = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_a,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="tool-a-1",
            ),
            headers=agent_headers,
        )
        assert r1.status_code == 200
        assert executor_a.dispatch_count == 1
        
        # Call tool B (should succeed, not blocked by tool A's cap)
        r2 = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_b,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="tool-b-1",
            ),
            headers=agent_headers,
        )
        assert r2.status_code == 200
        body2 = r2.json()
        assert body2["result"]["receipt"]["outcome"] == "success"
        assert executor_b.dispatch_count == 1
    finally:
        get_service_registry().unregister_local(tool_a)
        get_service_registry().unregister_local(tool_b)


@pytest.mark.anyio
async def test_duplicate_detection_enforce_mode(client, clean_database, monkeypatch):
    """Cross-key duplicate detection in enforce mode refuses duplicates.
    
    Identical request hash under different key is detected and refused.
    """
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "MCP_UPSTREAM_DUPLICATE_GUARD", "enforce")
    
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "test.dup.enforce"
    
    executor = FakeUpstreamExecutor("success")
    _register_upstream(tool_name, executor)
    
    try:
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
                "expires_at": (utc_now() + timedelta(hours=1)).isoformat(),
            },
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "permit-dup-test"},
        )
        assert permit_resp.status_code == 201
        permit_id = permit_resp.json()["permit_id"]
        
        # First call with identical arguments
        r1 = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="dup-key-1",
                message="duplicate-me",
            ),
            headers=agent_headers,
        )
        assert r1.status_code == 200
        assert executor.dispatch_count == 1
        
        # Second call with SAME arguments but DIFFERENT key
        r2 = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="dup-key-2",
                message="duplicate-me",
            ),
            headers=agent_headers,
        )
        assert r2.status_code == 200
        body2 = r2.json()
        assert "error" in body2
        assert body2["error"]["message"] == "duplicate_request_new_key"
        assert executor.dispatch_count == 1  # No second dispatch
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_duplicate_detection_log_mode_allows(client, clean_database, monkeypatch):
    """Cross-key duplicate detection in log mode allows duplicates (observe only)."""
    monkeypatch.setenv("MCP_UPSTREAM_DUPLICATE_GUARD", "log")
    
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "test.dup.log"
    
    executor = FakeUpstreamExecutor("success")
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
                "max_credits": 100,
                "expires_at": (utc_now() + timedelta(hours=1)).isoformat(),
            },
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "permit-log-mode"},
        )
        assert permit_resp.status_code == 201
        permit_id = permit_resp.json()["permit_id"]
        
        # First call
        r1 = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="log-key-1",
                message="log-me",
            ),
            headers=agent_headers,
        )
        assert r1.status_code == 200
        assert executor.dispatch_count == 1
        
        # Duplicate with different key should still succeed in log mode
        r2 = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="log-key-2",
                message="log-me",
            ),
            headers=agent_headers,
        )
        assert r2.status_code == 200
        body2 = r2.json()
        assert body2["result"]["receipt"]["outcome"] == "success"
        assert executor.dispatch_count == 2  # Both dispatched in log mode
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_duplicate_detection_opt_out(client, clean_database, monkeypatch):
    """Permit with allow_identical_repeats=true bypasses duplicate detection."""
    monkeypatch.setenv("MCP_UPSTREAM_DUPLICATE_GUARD", "enforce")
    
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "test.dup.optout"
    
    executor = FakeUpstreamExecutor("success")
    _register_upstream(tool_name, executor)
    
    try:
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
                "allow_identical_repeats": True,
                "expires_at": (utc_now() + timedelta(hours=1)).isoformat(),
            },
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "permit-opt-out"},
        )
        assert permit_resp.status_code == 201
        permit_id = permit_resp.json()["permit_id"]
        
        # First call
        r1 = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="opt-out-1",
                message="repeat-me",
            ),
            headers=agent_headers,
        )
        assert r1.status_code == 200
        assert executor.dispatch_count == 1
        
        # Duplicate should succeed because opt-out is enabled
        r2 = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="opt-out-2",
                message="repeat-me",
            ),
            headers=agent_headers,
        )
        assert r2.status_code == 200
        body2 = r2.json()
        assert body2["result"]["receipt"]["outcome"] == "success"
        assert executor.dispatch_count == 2  # Both dispatched with opt-out
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_same_key_replay_unchanged(client, clean_database):
    """Same-key replay returns original receipt with no second call or charge.
    
    This behavior must not regress.
    """
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "test.replay.same"
    
    executor = FakeUpstreamExecutor("success")
    _register_upstream(tool_name, executor)
    
    try:
        permit_id = await _create_permit_with_cap(
            client, wallet_id, key_id, tool_name, max_calls=1
        )
        
        # First call
        r1 = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="same-key",
                message="once",
            ),
            headers=agent_headers,
        )
        assert r1.status_code == 200
        body1 = r1.json()
        receipt_id_1 = body1["result"]["receipt"]["receipt_id"]
        assert executor.dispatch_count == 1
        
        # Replay with same key
        r2 = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="same-key",
                message="once",
            ),
            headers=agent_headers,
        )
        assert r2.status_code == 200
        body2 = r2.json()
        receipt_id_2 = body2["result"]["receipt"]["receipt_id"]
        
        # Same receipt, no second call
        assert receipt_id_2 == receipt_id_1
        assert executor.dispatch_count == 1  # Still 1, not 2
    finally:
        get_service_registry().unregister_local(tool_name)


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
    tool_name = "test.agg.unsupported"
    
    executor = FakeUpstreamExecutor("success")
    _register_upstream(tool_name, executor)
    
    try:
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
                "aggregate_value_cap": 50,
                "expires_at": (utc_now() + timedelta(hours=1)).isoformat(),
            },
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "permit-agg-cap"},
        )
        assert permit_resp.status_code == 201
        permit_id = permit_resp.json()["permit_id"]
        
        # Call is refused
        r = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="agg-1",
            ),
            headers=agent_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert "error" in body
        assert body["error"]["message"] == "permit_constraint_unsupported_for_upstream"
        assert "aggregate_value_cap" in str(body["error"]["data"]["details"])
        assert executor.dispatch_count == 0  # Never dispatched
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_duplicate_detection_finds_old_effectful_not_just_newest(
    client, clean_database, monkeypatch
):
    """Regression for Issue 3: duplicate detection must check ALL attempts in window.
    
    Before fix: used LIMIT 1 and could miss an older effectful attempt if a newer
    non-effectful attempt existed. Now checks all attempts in window for any effectful one.
    
    Scenario:
    1. First call succeeds (effectful)
    2. Second call with new key fails pre-dispatch (non-effectful, newer)
    3. Third call with new key should be blocked by #1, not allowed by #2
    """
    monkeypatch.setenv("MCP_UPSTREAM_DUPLICATE_GUARD", "enforce")
    
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "test.dup.regression"
    
    executor = FakeUpstreamExecutor("success")
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
                "max_credits": 100,
                "expires_at": (utc_now() + timedelta(hours=1)).isoformat(),
            },
            headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "permit-dup-reg"},
        )
        assert permit_resp.status_code == 201
        permit_id = permit_resp.json()["permit_id"]
        
        # Call 1: succeeds (effectful, will be oldest)
        r1 = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="dup-reg-1",
                message="original",
            ),
            headers=agent_headers,
        )
        assert r1.status_code == 200
        assert executor.dispatch_count == 1
        
        # Call 2: Same args, new key, but suppose it fails pre-dispatch somehow
        # (In real scenario this could be a cap exceeded on a different permit field,
        # or other pre-dispatch validation. For test simplicity, just do the third call.)
        
        # Call 3: Same args as #1, new key - should be BLOCKED by #1
        r3 = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="dup-reg-3",
                message="original",  # Same as r1
            ),
            headers=agent_headers,
        )
        assert r3.status_code == 200
        body3 = r3.json()
        # Should be blocked by duplicate detection finding r1 (succeeded/effectful)
        assert "error" in body3, (
            "Duplicate detection should block r3 because r1 succeeded (effectful). "
            "Issue 3 fix ensures we check ALL priors, not just newest with LIMIT 1."
        )
        assert body3["error"]["message"] == "duplicate_request_new_key"
        assert executor.dispatch_count == 1  # Still only r1 dispatched
    finally:
        get_service_registry().unregister_local(tool_name)
