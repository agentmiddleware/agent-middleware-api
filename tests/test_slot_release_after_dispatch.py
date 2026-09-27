"""Regression test: slots must not be released after confirmed dispatch.

Issue 1 (High): Slots were being refunded after a confirmed dispatch. A slot
must be released ONLY when the attempt is compensated before any dispatch;
dispatched, succeeded and delivery_uncertain must keep it.

This test verifies that an attempt that reaches 'returned_error' state AFTER
being dispatched (dispatched_at is set) does NOT release its call slot, even
when release_dispatch_budget_once is called.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import select

from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import McpDispatchAttemptModel, PermitModel, SigningKeyModel, WalletModel
from app.services.permits import PermitService


@pytest_asyncio.fixture
async def test_permit_with_cap():
    """Create a permit with max_calls_per_tool cap."""
    factory = get_session_factory()
    wallet_id = f"test-wallet-{uuid.uuid4().hex[:8]}"
    permit_id = f"test-permit-{uuid.uuid4().hex[:8]}"
    key_id = f"test-key-{uuid.uuid4().hex[:8]}"
    
    # Generate signing key
    private_key = Ed25519PrivateKey.generate()
    public_key_bytes = private_key.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw
    )
    import base64
    public_key_b64 = base64.b64encode(public_key_bytes).decode("ascii")
    
    async with factory() as session:
        async with session.begin():
            wallet = WalletModel(
                wallet_id=wallet_id,
                wallet_type="agent",
                balance=Decimal("100"),
                lifetime_credits=Decimal("100"),
            )
            session.add(wallet)
            
            signing_key = SigningKeyModel(
                key_id=key_id,
                alg="Ed25519",
                public_key_b64=public_key_b64,
                status="active",
                created_at=utc_now(),
            )
            session.add(signing_key)
            
            permit = PermitModel(
                permit_id=permit_id,
                issuer_wallet_id=wallet_id,
                subject_wallet_id=wallet_id,
                scopes_json=json.dumps(["mcp:invoke"]),
                allowed_tools_json=json.dumps(["test.tool"]),
                max_credits=Decimal("100"),
                spent_credits=Decimal("10"),
                expires_at=utc_now(),
                nonce=uuid.uuid4().hex,
                status="active",
                signature="test-sig",
                key_id=key_id,
                max_calls_per_tool_json=json.dumps({"test.tool": 1}),
                tool_call_counts_json=json.dumps({"test.tool": 1}),
            )
            session.add(permit)
    
    yield wallet_id, permit_id
    
    # Cleanup
    async with factory() as session:
        async with session.begin():
            await session.execute(
                select(PermitModel).where(PermitModel.permit_id == permit_id)
            )
            await session.execute(
                select(WalletModel).where(WalletModel.wallet_id == wallet_id)
            )


@pytest.mark.asyncio
async def test_slot_not_released_after_dispatch(test_permit_with_cap):
    """Regression: slots must not be released for dispatched attempts.
    
    An attempt that was dispatched (dispatched_at is set) and later returned
    an error should NOT release its call slot, because it actually consumed
    the slot during dispatch.
    """
    wallet_id, permit_id = test_permit_with_cap
    factory = get_session_factory()
    attempt_id = f"test-attempt-{uuid.uuid4().hex[:8]}"
    
    # Create a returned_error attempt that WAS dispatched
    async with factory() as session:
        async with session.begin():
            attempt = McpDispatchAttemptModel(
                attempt_id=attempt_id,
                idempotency_record_id=f"idem-{uuid.uuid4().hex[:8]}",
                wallet_id=wallet_id,
                permit_id=permit_id,
                public_tool_id="test.tool",
                upstream_tool_name="test.tool",
                upstream_origin="https://example.com",
                request_hash=uuid.uuid4().hex,
                credits_authorized=Decimal("10"),
                credits_charged=Decimal("10"),
                state="returned_error",
                call_slot_reserved=True,
                # Key: dispatched_at is set, meaning dispatch occurred
                dispatched_at=utc_now(),
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(attempt)
    
    # Get initial permit state
    async with factory() as session:
        permit = await session.get(PermitModel, permit_id)
        initial_counts = json.loads(permit.tool_call_counts_json or "{}")
        initial_spent = permit.spent_credits
    
    assert initial_counts.get("test.tool") == 1, "Initial slot count should be 1"
    
    # Try to release the slot via release_dispatch_budget_once
    permit_service = PermitService()
    released = await permit_service.release_dispatch_budget_once(attempt_id)
    
    # Should return False because dispatched_at is set
    assert released is False, (
        "release_dispatch_budget_once should return False for dispatched attempts"
    )
    
    # Verify slot was NOT released
    async with factory() as session:
        permit = await session.get(PermitModel, permit_id)
        final_counts = json.loads(permit.tool_call_counts_json or "{}")
        final_spent = permit.spent_credits
    
    assert final_counts.get("test.tool") == 1, (
        "Slot count should remain 1 - slot must NOT be released after dispatch"
    )
    assert final_spent == initial_spent, (
        "Budget should not be released for dispatched attempts"
    )


@pytest.mark.asyncio
async def test_slot_released_before_dispatch(test_permit_with_cap):
    """Control test: slots ARE released for pre-dispatch failures.
    
    An attempt that returned an error BEFORE dispatch (dispatched_at is NULL)
    should release its slot, because it never actually used it.
    """
    wallet_id, permit_id = test_permit_with_cap
    factory = get_session_factory()
    attempt_id = f"test-attempt-{uuid.uuid4().hex[:8]}"
    
    # Create a returned_error attempt that was NOT dispatched
    async with factory() as session:
        async with session.begin():
            attempt = McpDispatchAttemptModel(
                attempt_id=attempt_id,
                idempotency_record_id=f"idem-{uuid.uuid4().hex[:8]}",
                wallet_id=wallet_id,
                permit_id=permit_id,
                public_tool_id="test.tool",
                upstream_tool_name="test.tool",
                upstream_origin="https://example.com",
                request_hash=uuid.uuid4().hex,
                credits_authorized=Decimal("10"),
                credits_charged=Decimal("0"),
                state="returned_error",
                call_slot_reserved=True,
                # Key: dispatched_at is NULL, meaning dispatch never happened
                dispatched_at=None,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(attempt)
    
    # Get initial permit state
    async with factory() as session:
        permit = await session.get(PermitModel, permit_id)
        initial_counts = json.loads(permit.tool_call_counts_json or "{}")
        initial_spent = permit.spent_credits
    
    assert initial_counts.get("test.tool") == 1, "Initial slot count should be 1"
    
    # Try to release the slot via release_dispatch_budget_once
    permit_service = PermitService()
    released = await permit_service.release_dispatch_budget_once(attempt_id)
    
    # Should return True because dispatched_at is NULL
    assert released is True, (
        "release_dispatch_budget_once should return True for pre-dispatch failures"
    )
    
    # Verify slot WAS released
    async with factory() as session:
        permit = await session.get(PermitModel, permit_id)
        final_counts = json.loads(permit.tool_call_counts_json or "{}")
        final_spent = permit.spent_credits
    
    assert final_counts.get("test.tool") == 0, (
        "Slot count should be 0 - slot MUST be released for pre-dispatch failures"
    )
    assert final_spent < initial_spent, "Budget should be released"
