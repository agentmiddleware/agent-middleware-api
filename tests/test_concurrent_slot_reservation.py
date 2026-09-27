"""Regression test: tool_call_counts_json writes must be atomic (CAS).

Issue 2 (High): The tool_call_counts_json write was not compare-and-swap, so
concurrent reservations could clobber each other. This test proves that N
parallel new-key calls with cap=1 give exactly one dispatch on Postgres.

This test must run against real Postgres to verify row-level locking and CAS
behavior. SQLite does not support SELECT FOR UPDATE.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from httpx import ASGITransport, AsyncClient

from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import PermitModel, SigningKeyModel, WalletModel
from app.main import app

# Skip if not running against Postgres
pytestmark = pytest.mark.skipif(
    os.getenv("DATABASE_URL", "").startswith("sqlite"),
    reason="Postgres-only test for row locking and CAS semantics",
)


@pytest.fixture
async def postgres_test_setup():
    """Set up wallet, permit, and signing key for concurrent tests."""
    factory = get_session_factory()
    wallet_id = f"test-wallet-{uuid.uuid4().hex[:8]}"
    permit_id = f"test-permit-{uuid.uuid4().hex[:8]}"
    key_id = f"test-key-{uuid.uuid4().hex[:8]}"
    
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
            
            # Create permit with max_calls_per_tool cap of 1 for test.tool
            permit = PermitModel(
                permit_id=permit_id,
                issuer_wallet_id=wallet_id,
                subject_wallet_id=wallet_id,
                scopes_json=json.dumps(["mcp:invoke"]),
                allowed_tools_json=json.dumps(["test.tool"]),
                max_credits=Decimal("1000"),
                spent_credits=Decimal("0"),
                expires_at=utc_now(),
                nonce=uuid.uuid4().hex,
                status="active",
                signature="test-sig",
                key_id=key_id,
                max_calls_per_tool_json=json.dumps({"test.tool": 1}),
                tool_call_counts_json=json.dumps({}),
            )
            session.add(permit)
    
    yield wallet_id, permit_id, key_id
    
    # Cleanup handled by test database isolation


@pytest.mark.asyncio
async def test_concurrent_reservations_cap_one_postgres(postgres_test_setup):
    """N parallel new-key calls with cap=1 give exactly one dispatch.
    
    This is the core regression test for Issue 2. Without CAS on
    tool_call_counts_json, multiple concurrent reservations could all see
    count=0, all increment to count=1, and all succeed - violating the cap.
    
    With proper CAS, only one reservation succeeds and the rest fail with
    permit_max_calls_exceeded.
    """
    wallet_id, permit_id, key_id = postgres_test_setup
    
    # Register upstream tool for dispatch
    from app.services.service_registry import get_service_registry
    registry = get_service_registry()
    
    # Mock upstream executor that succeeds
    class FakeUpstreamExecutor:
        async def execute(self, tool_name: str, arguments: dict) -> dict:
            return {"result": "success"}
    
    registry._register_upstream(
        "test.tool",
        FakeUpstreamExecutor(),
        origin="https://test.example.com",
    )
    
    try:
        # Launch N concurrent requests with different idempotency keys
        N = 10
        
        async def make_request(index: int) -> tuple[int, dict]:
            """Make one governed invoke request."""
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/mcp/invoke",
                    headers={
                        "X-Agent-Middleware-Wallet-ID": wallet_id,
                        "X-Agent-Middleware-Permit-ID": permit_id,
                        "X-Idempotency-Key": f"test-key-{index}-{uuid.uuid4().hex[:8]}",
                    },
                    json={
                        "tool": "test.tool",
                        "arguments": {"index": index},
                    },
                )
                return response.status_code, response.json()
        
        # Execute all requests concurrently
        results = await asyncio.gather(
            *[make_request(i) for i in range(N)],
            return_exceptions=True
        )
        
        # Analyze results
        successes = []
        cap_exceeded = []
        errors = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                errors.append((i, str(result)))
            else:
                status, body = result
                if status == 200:
                    successes.append((i, body))
                elif status == 402:  # Payment required / cap exceeded
                    if "permit_max_calls_exceeded" in body.get("error", {}).get("code", ""):
                        cap_exceeded.append((i, body))
                    else:
                        errors.append((i, body))
                else:
                    errors.append((i, body))
        
        # Verify exactly one success
        assert len(successes) == 1, (
            f"Expected exactly 1 success, got {len(successes)}. "
            f"Without CAS, multiple reservations would succeed. "
            f"Successes: {successes}, "
            f"Cap exceeded: {len(cap_exceeded)}, "
            f"Errors: {errors}"
        )
        
        # All others should be denied with permit_max_calls_exceeded
        assert len(cap_exceeded) == N - 1, (
            f"Expected {N-1} cap exceeded responses, got {len(cap_exceeded)}. "
            f"Cap exceeded: {cap_exceeded}, "
            f"Errors: {errors}"
        )
        
        # No unexpected errors
        assert len(errors) == 0, f"Unexpected errors: {errors}"
        
        # Verify final permit state
        factory = get_session_factory()
        async with factory() as session:
            permit = await session.get(PermitModel, permit_id)
            final_counts = json.loads(permit.tool_call_counts_json or "{}")
        
        assert final_counts.get("test.tool") == 1, (
            f"Final count should be exactly 1, got {final_counts.get('test.tool')}. "
            "Without CAS, count could be 1 but N>1 requests succeeded (clobbered)."
        )
    
    finally:
        registry.unregister_local("test.tool")


@pytest.mark.asyncio  
async def test_concurrent_releases_atomic_postgres(postgres_test_setup):
    """Concurrent slot releases must use CAS to avoid clobbering each other.
    
    This test verifies that the release path also uses CAS on
    tool_call_counts_json, preventing concurrent releases from clobbering
    each other's decrements.
    """
    wallet_id, permit_id, key_id = postgres_test_setup
    factory = get_session_factory()
    
    # Set initial count to N
    N = 5
    async with factory() as session:
        async with session.begin():
            permit = await session.get(PermitModel, permit_id)
            permit.tool_call_counts_json = json.dumps({"test.tool": N})
            session.add(permit)
    
    # Create N returned_error attempts (pre-dispatch failures) with slots reserved
    attempt_ids = []
    from app.db.models import McpDispatchAttemptModel
    
    async with factory() as session:
        async with session.begin():
            for i in range(N):
                attempt_id = f"test-attempt-{i}-{uuid.uuid4().hex[:8]}"
                attempt_ids.append(attempt_id)
                
                attempt = McpDispatchAttemptModel(
                    attempt_id=attempt_id,
                    idempotency_record_id=f"idem-{i}-{uuid.uuid4().hex[:8]}",
                    wallet_id=wallet_id,
                    permit_id=permit_id,
                    public_tool_id="test.tool",
                    upstream_tool_name="test.tool",
                    upstream_origin="https://test.example.com",
                    request_hash=uuid.uuid4().hex,
                    credits_authorized=Decimal("10"),
                    credits_charged=Decimal("0"),
                    state="returned_error",
                    call_slot_reserved=True,
                    dispatched_at=None,  # Pre-dispatch failure
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
                session.add(attempt)
    
    # Release all N slots concurrently
    from app.services.permits import PermitService
    permit_service = PermitService()
    
    async def release_slot(attempt_id: str) -> bool:
        try:
            return await permit_service.release_dispatch_budget_once(attempt_id)
        except Exception as exc:
            return exc
    
    results = await asyncio.gather(
        *[release_slot(aid) for aid in attempt_ids],
        return_exceptions=False
    )
    
    # All releases should succeed (return True)
    successful_releases = sum(1 for r in results if r is True)
    assert successful_releases == N, (
        f"Expected all {N} releases to succeed, got {successful_releases}. "
        f"Results: {results}"
    )
    
    # Verify final count is 0
    async with factory() as session:
        permit = await session.get(PermitModel, permit_id)
        final_counts = json.loads(permit.tool_call_counts_json or "{}")
    
    assert final_counts.get("test.tool") == 0, (
        f"Final count should be 0 after {N} releases, got {final_counts.get('test.tool')}. "
        "Without CAS on release, concurrent decrements could clobber each other."
    )
