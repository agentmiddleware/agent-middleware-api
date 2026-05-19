from __future__ import annotations

import pytest

from app.services.idempotency import (
    IdempotencyConflictError,
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
