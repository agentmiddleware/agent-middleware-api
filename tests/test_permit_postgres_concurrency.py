"""Postgres-only concurrency tests for permit call slot enforcement.

Tests that multiple concurrent calls with different idempotency keys
correctly enforce per-tool call caps under real database concurrency.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.time import utc_now
from app.db.database import get_session_factory
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.service_registry import get_service_registry
from app.services.upstream_mcp import (
    UpstreamMcpDeliveryUncertainError,
    UpstreamMcpResult,
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
class ConcurrentUpstreamExecutor:
    """Executor that can delay dispatch to test concurrency."""
    mode: str = "success"
    calls: list[dict[str, Any]] = field(default_factory=list)
    dispatch_count: int = 0
    delay_seconds: float = 0.0
    
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
        
        # Delay to ensure concurrent calls overlap
        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)
        
        await before_dispatch()
        self.dispatch_count += 1
        
        if self.mode == "delivery_uncertain":
            raise UpstreamMcpDeliveryUncertainError()
        
        return _upstream_result(
            {"content": [{"type": "text", "text": "success"}], "isError": False}
        )


def _register_upstream(
    tool_name: str,
    executor: ConcurrentUpstreamExecutor,
    *,
    credits_per_call: float = 2.0,
) -> None:
    get_service_registry().register_upstream(
        service_id=tool_name,
        name="Test Concurrent Upstream Tool",
        description="Test upstream tool for concurrency enforcement",
        category=ServiceCategory.AGENT_COMMS,
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
            "expires_at": (utc_now() + timedelta(hours=1)).isoformat(),
        },
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": f"permit-cap-{tool_name}-{max_calls}"},
    )
    assert permit_resp.status_code == 201
    return permit_resp.json()["permit_id"]


@pytest.mark.anyio
@pytest.mark.skipif(
    "sqlite" in str(get_session_factory().kw.get("bind", "")).lower(),
    reason="Postgres-only concurrency test",
)
async def test_concurrent_remote_cap_1_allows_exactly_one_dispatch(client, clean_database):
    """10 parallel new-key calls on cap=1 remote tool: exactly 1 dispatch.
    
    This is the critical Postgres concurrency test proving that the per-tool
    call cap is correctly enforced under concurrent load. The row lock on
    the permit serializes reservation attempts, so exactly one succeeds and
    dispatches while the rest are denied with permit_max_calls_exceeded.
    """
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "test.concurrent.cap1"
    
    # Delay dispatch slightly to ensure all calls overlap at reservation
    executor = ConcurrentUpstreamExecutor("success", delay_seconds=0.05)
    _register_upstream(tool_name, executor)
    
    try:
        permit_id = await _create_permit_with_cap(
            client, wallet_id, key_id, tool_name, max_calls=1
        )
        
        # Launch 10 concurrent calls with different keys
        async def make_call(key_suffix: int):
            return await client.post(
                "/mcp/messages",
                json=_call_body(
                    tool_name=tool_name,
                    wallet_id=wallet_id,
                    permit_id=permit_id,
                    idempotency_key=f"concurrent-{key_suffix}",
                    message=f"call-{key_suffix}",
                ),
                headers=agent_headers,
            )
        
        responses = await asyncio.gather(*[make_call(i) for i in range(10)])
        
        # Count successes and denials
        successes = []
        denials = []
        for i, resp in enumerate(responses):
            assert resp.status_code == 200
            body = resp.json()
            if "result" in body:
                successes.append(i)
            elif "error" in body and body["error"]["message"] == "permit_max_calls_exceeded":
                denials.append(i)
        
        # Exactly one should succeed
        assert len(successes) == 1, (
            f"Expected exactly 1 success, got {len(successes)}: {successes}. "
            f"Denials: {len(denials)}"
        )
        assert len(denials) == 9, f"Expected 9 denials, got {len(denials)}"
        
        # Exactly one dispatch
        assert executor.dispatch_count == 1, (
            f"Expected exactly 1 dispatch, got {executor.dispatch_count}"
        )
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
@pytest.mark.skipif(
    "sqlite" in str(get_session_factory().kw.get("bind", "")).lower(),
    reason="Postgres-only concurrency test",
)
async def test_concurrent_remote_cap_1_with_delivery_uncertain_blocks_all(client, clean_database):
    """Cap=1 held by delivery_uncertain attempt blocks all new calls.
    
    Variant of the concurrency test where the first call results in
    delivery_uncertain. Its slot is held (never released), so all
    subsequent concurrent calls should be denied.
    """
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    key_id = provisioned["key_id"]
    agent_headers = provisioned["agent_headers"]
    tool_name = "test.concurrent.uncertain"
    
    executor = ConcurrentUpstreamExecutor("delivery_uncertain", delay_seconds=0.05)
    _register_upstream(tool_name, executor)
    
    try:
        permit_id = await _create_permit_with_cap(
            client, wallet_id, key_id, tool_name, max_calls=1
        )
        
        # First call: delivery_uncertain (holds the slot)
        r1 = await client.post(
            "/mcp/messages",
            json=_call_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                permit_id=permit_id,
                idempotency_key="uncertain-0",
            ),
            headers=agent_headers,
        )
        assert r1.status_code == 200
        body1 = r1.json()
        assert "error" in body1
        assert body1["error"]["message"] == "delivery_uncertain"
        assert executor.dispatch_count == 1
        
        # Launch 10 more concurrent calls
        async def make_call(key_suffix: int):
            return await client.post(
                "/mcp/messages",
                json=_call_body(
                    tool_name=tool_name,
                    wallet_id=wallet_id,
                    permit_id=permit_id,
                    idempotency_key=f"concurrent-{key_suffix}",
                ),
                headers=agent_headers,
            )
        
        responses = await asyncio.gather(*[make_call(i) for i in range(10)])
        
        # All should be denied
        for i, resp in enumerate(responses):
            assert resp.status_code == 200
            body = resp.json()
            assert "error" in body, f"Call {i} should be denied"
            assert body["error"]["message"] == "permit_max_calls_exceeded", (
                f"Call {i} should be denied with permit_max_calls_exceeded"
            )
        
        # Still only 1 dispatch (the delivery_uncertain one)
        assert executor.dispatch_count == 1
    finally:
        get_service_registry().unregister_local(tool_name)
