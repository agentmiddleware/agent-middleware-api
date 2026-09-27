"""Regression test: duplicate detection must check ALL effectful attempts.

Issue 3 (Medium): Duplicate detection was using LIMIT 1 and could skip an older
effectful attempt if a newer non-effectful attempt existed. It must consider any
prior effectful attempt (dispatched, succeeded, or delivery_uncertain) in the
window, not just the newest attempt.

Scenario:
1. Attempt A at T0: dispatched, succeeded (effectful) 
2. Attempt B at T1: prepared, returned_error before dispatch (not effectful)
3. Attempt C at T2: new duplicate

Before fix: Query returns B (newest with LIMIT 1), sees it's not effectful,
allows C - but A was effectful and should block!

After fix: Query returns all, finds A is effectful, blocks C.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from httpx import ASGITransport, AsyncClient

from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import (
    IdempotencyRecordModel,
    McpDispatchAttemptModel,
    PermitModel,
    SigningKeyModel,
    WalletModel,
)
from app.main import app


@pytest.fixture
async def dup_test_setup():
    """Set up wallet, permit, and test scenario for duplicate detection."""
    factory = get_session_factory()
    wallet_id = f"test-wallet-{uuid.uuid4().hex[:8]}"
    permit_id = f"test-permit-{uuid.uuid4().hex[:8]}"
    key_id = f"test-key-{uuid.uuid4().hex[:8]}"
    public_tool_id = "test.dup.tool"
    request_hash = f"req-{uuid.uuid4().hex}"
    
    # Generate signing key
    private_key = Ed25519PrivateKey.generate()
    public_key_bytes = private_key.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw
    )
    public_key_b64 = base64.b64encode(public_key_bytes).decode("ascii")
    
    async with factory() as session:
        async with session.begin():
            # Create wallet
            wallet = WalletModel(
                wallet_id=wallet_id,
                wallet_type="agent",
                balance=Decimal("1000"),
                lifetime_credits=Decimal("1000"),
            )
            session.add(wallet)
            
            # Create signing key
            signing_key = SigningKeyModel(
                key_id=key_id,
                alg="Ed25519",
                public_key_b64=public_key_b64,
                status="active",
                created_at=utc_now(),
            )
            session.add(signing_key)
            
            # Create permit (no max_calls_per_tool cap)
            permit = PermitModel(
                permit_id=permit_id,
                issuer_wallet_id=wallet_id,
                subject_wallet_id=wallet_id,
                scopes_json=json.dumps(["mcp:invoke"]),
                allowed_tools_json=json.dumps([public_tool_id]),
                max_credits=Decimal("1000"),
                spent_credits=Decimal("0"),
                expires_at=utc_now() + timedelta(hours=1),
                nonce=uuid.uuid4().hex,
                status="active",
                signature="test-sig",
                key_id=key_id,
                allow_identical_repeats=False,  # Duplicate detection enabled
            )
            session.add(permit)
    
    yield wallet_id, permit_id, key_id, public_tool_id, request_hash
    
    # Cleanup handled by test database isolation


@pytest.mark.asyncio
async def test_duplicate_detection_finds_old_effectful_attempt(dup_test_setup):
    """Duplicate detection must check ALL attempts, not just newest.
    
    Create:
    1. Old effectful attempt (succeeded)
    2. Newer non-effectful attempt (returned_error before dispatch)
    3. Try new duplicate
    
    Without fix: Only checks newest attempt (non-effectful), allows duplicate.
    With fix: Checks all attempts, finds old effectful one, blocks duplicate.
    """
    wallet_id, permit_id, key_id, public_tool_id, request_hash = dup_test_setup
    factory = get_session_factory()
    now = utc_now()
    
    # Create scenario in database
    async with factory() as session:
        async with session.begin():
            # Attempt A (T0): Effectful - dispatched and succeeded
            attempt_a_id = f"attempt-a-{uuid.uuid4().hex[:8]}"
            idem_a_id = f"idem-a-{uuid.uuid4().hex[:8]}"
            
            idem_a = IdempotencyRecordModel(
                record_id=idem_a_id,
                wallet_id=wallet_id,
                endpoint="/mcp/invoke",
                idempotency_key=f"key-a-{uuid.uuid4().hex[:8]}",
                request_hash=request_hash,
                operation_kind="governed_mcp_invoke",
                response_reference=f"rcpt-a-{uuid.uuid4().hex[:8]}",
                status_code=200,
                created_at=now - timedelta(minutes=5),
            )
            session.add(idem_a)
            
            attempt_a = McpDispatchAttemptModel(
                attempt_id=attempt_a_id,
                idempotency_record_id=idem_a_id,
                wallet_id=wallet_id,
                permit_id=permit_id,
                public_tool_id=public_tool_id,
                upstream_tool_name=public_tool_id,
                upstream_origin="https://test.example.com",
                request_hash=request_hash,
                credits_authorized=Decimal("10"),
                credits_charged=Decimal("10"),
                state="succeeded",  # Effectful terminal state
                dispatched_at=now - timedelta(minutes=5),  # Was dispatched
                completed_at=now - timedelta(minutes=4),
                created_at=now - timedelta(minutes=5),
                updated_at=now - timedelta(minutes=4),
            )
            session.add(attempt_a)
            
            # Attempt B (T1): Non-effectful - returned error before dispatch
            attempt_b_id = f"attempt-b-{uuid.uuid4().hex[:8]}"
            idem_b_id = f"idem-b-{uuid.uuid4().hex[:8]}"
            
            idem_b = IdempotencyRecordModel(
                record_id=idem_b_id,
                wallet_id=wallet_id,
                endpoint="/mcp/invoke",
                idempotency_key=f"key-b-{uuid.uuid4().hex[:8]}",
                request_hash=request_hash,
                operation_kind="governed_mcp_invoke",
                response_reference=f"rcpt-b-{uuid.uuid4().hex[:8]}",
                status_code=402,
                created_at=now - timedelta(minutes=2),
            )
            session.add(idem_b)
            
            attempt_b = McpDispatchAttemptModel(
                attempt_id=attempt_b_id,
                idempotency_record_id=idem_b_id,
                wallet_id=wallet_id,
                permit_id=permit_id,
                public_tool_id=public_tool_id,
                upstream_tool_name=public_tool_id,
                upstream_origin="https://test.example.com",
                request_hash=request_hash,
                credits_authorized=Decimal("10"),
                credits_charged=Decimal("0"),
                state="returned_error",  # Terminal but...
                dispatched_at=None,  # Never dispatched = non-effectful
                created_at=now - timedelta(minutes=2),
                updated_at=now - timedelta(minutes=2),
            )
            session.add(attempt_b)
    
    # Now try attempt C with new idempotency key but same request_hash
    # This should be BLOCKED because attempt A was effectful
    
    # Register mock upstream
    from app.services.service_registry import get_service_registry
    registry = get_service_registry()
    
    class FakeUpstreamExecutor:
        async def execute(self, tool_name: str, arguments: dict) -> dict:
            return {"result": "success"}
    
    registry._register_upstream(
        public_tool_id,
        FakeUpstreamExecutor(),
        origin="https://test.example.com",
    )
    
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Set MCP_UPSTREAM_DUPLICATE_GUARD to enforce mode
            import os
            original_mode = os.environ.get("MCP_UPSTREAM_DUPLICATE_GUARD")
            os.environ["MCP_UPSTREAM_DUPLICATE_GUARD"] = "enforce"
            
            try:
                response = await client.post(
                    "/mcp/invoke",
                    headers={
                        "X-Agent-Middleware-Wallet-ID": wallet_id,
                        "X-Agent-Middleware-Permit-ID": permit_id,
                        "X-Idempotency-Key": f"key-c-{uuid.uuid4().hex[:8]}",
                    },
                    json={
                        "tool": public_tool_id,
                        "arguments": {"test": "duplicate"},
                    },
                )
            finally:
                # Restore original setting
                if original_mode is None:
                    os.environ.pop("MCP_UPSTREAM_DUPLICATE_GUARD", None)
                else:
                    os.environ["MCP_UPSTREAM_DUPLICATE_GUARD"] = original_mode
        
        # Should be denied due to duplicate detection finding attempt A
        assert response.status_code == 402, (
            f"Expected 402 (duplicate blocked), got {response.status_code}. "
            f"Response: {response.json()}. "
            f"Without fix, would only check newest attempt B (non-effectful) "
            f"and allow the duplicate, missing old effectful attempt A."
        )
        
        body = response.json()
        assert "permit_duplicate_request_prevented" in body.get("error", {}).get(
            "code", ""
        ), (
            f"Expected duplicate prevention error, got: {body}. "
            f"The fix ensures we check ALL prior attempts, not just the newest."
        )
    
    finally:
        registry.unregister_local(public_tool_id)


@pytest.mark.asyncio
async def test_duplicate_detection_control_all_noneffectful(dup_test_setup):
    """Control test: if ALL prior attempts are non-effectful, allow duplicate.
    
    This verifies the fix doesn't break the intended behavior: if no prior
    attempt was effectful, a new duplicate should be allowed (in log mode) or
    only blocked for policy reasons (in enforce mode), but not because of an
    effectful attempt.
    """
    wallet_id, permit_id, key_id, public_tool_id, request_hash = dup_test_setup
    factory = get_session_factory()
    now = utc_now()
    
    # Create two non-effectful attempts
    async with factory() as session:
        async with session.begin():
            for i in range(2):
                attempt_id = f"attempt-{i}-{uuid.uuid4().hex[:8]}"
                idem_id = f"idem-{i}-{uuid.uuid4().hex[:8]}"
                
                idem = IdempotencyRecordModel(
                    record_id=idem_id,
                    wallet_id=wallet_id,
                    endpoint="/mcp/invoke",
                    idempotency_key=f"key-{i}-{uuid.uuid4().hex[:8]}",
                    request_hash=request_hash,
                    operation_kind="governed_mcp_invoke",
                    response_reference=f"rcpt-{i}-{uuid.uuid4().hex[:8]}",
                    status_code=402,
                    created_at=now - timedelta(minutes=5 - i),
                )
                session.add(idem)
                
                attempt = McpDispatchAttemptModel(
                    attempt_id=attempt_id,
                    idempotency_record_id=idem_id,
                    wallet_id=wallet_id,
                    permit_id=permit_id,
                    public_tool_id=public_tool_id,
                    upstream_tool_name=public_tool_id,
                    upstream_origin="https://test.example.com",
                    request_hash=request_hash,
                    credits_authorized=Decimal("10"),
                    credits_charged=Decimal("0"),
                    state="returned_error",
                    dispatched_at=None,  # None are effectful
                    created_at=now - timedelta(minutes=5 - i),
                    updated_at=now - timedelta(minutes=5 - i),
                )
                session.add(attempt)
    
    # Register mock upstream
    from app.services.service_registry import get_service_registry
    registry = get_service_registry()
    
    class FakeUpstreamExecutor:
        async def execute(self, tool_name: str, arguments: dict) -> dict:
            return {"result": "success"}
    
    registry._register_upstream(
        public_tool_id,
        FakeUpstreamExecutor(),
        origin="https://test.example.com",
    )
    
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Use log mode (default) - should allow
            import os
            original_mode = os.environ.get("MCP_UPSTREAM_DUPLICATE_GUARD")
            os.environ["MCP_UPSTREAM_DUPLICATE_GUARD"] = "log"
            
            try:
                response = await client.post(
                    "/mcp/invoke",
                    headers={
                        "X-Agent-Middleware-Wallet-ID": wallet_id,
                        "X-Agent-Middleware-Permit-ID": permit_id,
                        "X-Idempotency-Key": f"key-new-{uuid.uuid4().hex[:8]}",
                    },
                    json={
                        "tool": public_tool_id,
                        "arguments": {"test": "duplicate"},
                    },
                )
            finally:
                if original_mode is None:
                    os.environ.pop("MCP_UPSTREAM_DUPLICATE_GUARD", None)
                else:
                    os.environ["MCP_UPSTREAM_DUPLICATE_GUARD"] = original_mode
        
        # Should succeed because no prior effectful attempts exist
        assert response.status_code == 200, (
            f"Expected 200 (allowed - no effectful priors), got {response.status_code}. "
            f"Response: {response.json()}"
        )
    
    finally:
        registry.unregister_local(public_tool_id)
