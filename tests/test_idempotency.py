from __future__ import annotations

import asyncio

import pytest

from app.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyReplay,
    get_idempotency_service,
)
from app.services.agent_money import get_agent_money


@pytest.mark.anyio
async def test_idempotency_replays_same_payload_and_rejects_different_payload(
    clean_database,
):
    service = get_idempotency_service()
    wallet = await get_agent_money().create_sponsor_wallet(
        sponsor_name="Idempotency Sponsor",
        email="idem@example.com",
    )
    first = await service.begin(
        wallet_id=wallet.wallet_id,
        endpoint="/v1/test",
        idempotency_key="same-key",
        request_payload={"amount": 1},
    )
    assert first is None
    await service.complete(
        wallet_id=wallet.wallet_id,
        endpoint="/v1/test",
        idempotency_key="same-key",
        response_reference="receipt-1",
        response_json={"receipt_id": "receipt-1"},
    )

    replay = await service.begin(
        wallet_id=wallet.wallet_id,
        endpoint="/v1/test",
        idempotency_key="same-key",
        request_payload={"amount": 1},
    )
    assert replay is not None
    assert replay.response_reference == "receipt-1"
    assert replay.response_json == {"receipt_id": "receipt-1"}

    with pytest.raises(IdempotencyConflictError):
        await service.begin(
            wallet_id=wallet.wallet_id,
            endpoint="/v1/test",
            idempotency_key="same-key",
            request_payload={"amount": 2},
        )


@pytest.mark.anyio
async def test_idempotency_fails_closed_for_in_progress_record(clean_database):
    service = get_idempotency_service()
    wallet = await get_agent_money().create_sponsor_wallet(
        sponsor_name="In Progress Idempotency Sponsor",
        email="idem-in-progress@example.com",
    )
    first = await service.begin(
        wallet_id=wallet.wallet_id,
        endpoint="/v1/test",
        idempotency_key="in-progress-key",
        request_payload={"amount": 1},
    )
    assert first is None

    with pytest.raises(IdempotencyInProgressError) as exc_info:
        await service.begin(
            wallet_id=wallet.wallet_id,
            endpoint="/v1/test",
            idempotency_key="in-progress-key",
            request_payload={"amount": 1},
        )
    assert str(exc_info.value) == "idempotency_in_progress"


@pytest.mark.anyio
async def test_concurrent_begin_with_same_key_never_raises_unhandled_error(
    clean_database,
):
    """Two requests racing on the same idempotency key must not surface a raw
    IntegrityError (500) to either caller — one starts, the other observes
    either the in-progress state or a completed replay."""
    service = get_idempotency_service()
    wallet = await get_agent_money().create_sponsor_wallet(
        sponsor_name="Concurrent Idempotency Sponsor",
        email="idem-concurrent@example.com",
    )

    results = await asyncio.gather(
        *[
            service.begin(
                wallet_id=wallet.wallet_id,
                endpoint="/v1/test",
                idempotency_key="race-key",
                request_payload={"amount": 1},
            )
            for _ in range(5)
        ],
        return_exceptions=True,
    )

    for result in results:
        if isinstance(result, Exception):
            assert isinstance(
                result, (IdempotencyInProgressError, IdempotencyConflictError)
            )
        else:
            assert result is None or isinstance(result, IdempotencyReplay)

    started = [r for r in results if r is None]
    assert len(started) == 1
