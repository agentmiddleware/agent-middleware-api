from dataclasses import replace

import pytest

from app.services.action_permits import action_execution_identity
from app.services.agent_money import get_agent_money
from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    get_idempotency_service,
)
from tests.test_action_invocation import action_permit
from tests.test_action_permits import BINDING


@pytest.mark.anyio
async def test_action_owner_excludes_legacy_and_other_wallets(clean_database):
    wallet = await get_agent_money().create_sponsor_wallet(
        sponsor_name="Action Owner", email="action@example.invalid"
    )
    service = get_idempotency_service()
    identity = action_execution_identity(
        action_permit(subject_wallet_id=wallet.wallet_id), BINDING
    )
    for endpoint in ["/mcp/invoke", "/mcp/messages", "/mcp/tools/partner.pay/invoke"]:
        # The canonical governed index forbids these three together. Distinct
        # caller keys prove lookup never searches any of these namespaces.
        key = identity.idempotency_key if endpoint == "/mcp/invoke" else endpoint
        await service.begin_with_record(
            wallet_id=wallet.wallet_id,
            endpoint=endpoint,
            idempotency_key=key,
            request_payload=identity.request_payload,
        )
    assert (
        await service.get_action_record(
            wallet_id=wallet.wallet_id, internal_key=identity.idempotency_key
        )
        is None
    )
    begun = await service.begin_action_with_record(
        wallet_id=wallet.wallet_id, identity=identity
    )
    record = await service.get_action_record(
        wallet_id=wallet.wallet_id, internal_key=identity.idempotency_key
    )
    assert record is not None and record.record_id == begun.record_id
    assert record.endpoint == "/mcp/action/v1"
    assert record.operation_kind == "upstream_mcp"
    assert (
        await service.get_action_record(
            wallet_id="foreign", internal_key=identity.idempotency_key
        )
        is None
    )
    legacy = await service.get_governed_mcp_record(
        wallet_id=wallet.wallet_id, idempotency_key=identity.idempotency_key
    )
    assert legacy is not None and legacy.record_id != record.record_id
    original_hash = record.request_hash
    with pytest.raises(IdempotencyInProgressError):
        await service.begin_action_with_record(
            wallet_id=wallet.wallet_id, identity=identity
        )
    changed = replace(
        identity,
        request_payload={**identity.request_payload, "action_payload_hash": "b" * 64},
    )
    with pytest.raises(IdempotencyConflictError):
        await service.begin_action_with_record(
            wallet_id=wallet.wallet_id, identity=changed
        )
    await service.complete_action(
        wallet_id=wallet.wallet_id,
        internal_key=identity.idempotency_key,
        response_reference="receipt-fixture",
        response_json={"done": True},
    )
    replay = await service.begin_action_with_record(
        wallet_id=wallet.wallet_id, identity=identity
    )
    assert replay.record_id == begun.record_id and replay.request_hash == original_hash
    assert replay.replay is not None and replay.replay.response_json == {"done": True}
    record = await service.get_action_record(
        wallet_id=wallet.wallet_id, internal_key=identity.idempotency_key
    )
    assert record is not None and record.request_hash == original_hash
    assert (
        await service.get_governed_mcp_record(
            wallet_id=wallet.wallet_id, idempotency_key=identity.idempotency_key
        )
    ).response_json is None


@pytest.mark.anyio
async def test_action_begin_refuses_wrong_namespace_before_database():
    service = get_idempotency_service()
    identity = action_execution_identity(action_permit(), BINDING)
    with pytest.raises(ValueError, match="invalid_action_execution_namespace"):
        await service.begin_action_with_record(
            wallet_id=identity.request_payload["subject_wallet_id"],
            identity=replace(identity, endpoint="/mcp/invoke"),
        )


@pytest.mark.anyio
async def test_concurrent_action_begin_keeps_one_owner(clean_database):
    import asyncio

    wallet = await get_agent_money().create_sponsor_wallet(
        sponsor_name="Action Race", email="action-race@example.invalid"
    )
    service = get_idempotency_service()
    identity = action_execution_identity(
        action_permit(subject_wallet_id=wallet.wallet_id), BINDING
    )

    async def begin():
        try:
            return await service.begin_action_with_record(
                wallet_id=wallet.wallet_id, identity=identity
            )
        except IdempotencyInProgressError:
            return None

    results = await asyncio.gather(*(begin() for _ in range(4)))
    owners = [result for result in results if result is not None]
    assert len(owners) == 1
    record = await service.get_action_record(
        wallet_id=wallet.wallet_id, internal_key=identity.idempotency_key
    )
    assert record is not None and record.record_id == owners[0].record_id
    assert record.request_hash == owners[0].request_hash
    await service.complete_action(
        wallet_id=wallet.wallet_id,
        internal_key=identity.idempotency_key,
        response_reference=None,
        response_json={"done": True},
    )
    replay = await service.begin_action_with_record(
        wallet_id=wallet.wallet_id, identity=identity
    )
    assert (
        replay.record_id == record.record_id
        and replay.request_hash == record.request_hash
    )


@pytest.mark.anyio
async def test_action_begin_refuses_foreign_wallet_before_database():
    identity = action_execution_identity(action_permit(), BINDING)
    with pytest.raises(ValueError, match="action_execution_wallet_mismatch"):
        await get_idempotency_service().begin_action_with_record(
            wallet_id="foreign", identity=identity
        )
