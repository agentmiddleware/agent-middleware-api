"""Backlog #8: a claim that races permit activation is REJECTED, never parked.

"Activation" is the commit of the permit row (``PermitService.create_permit``
or ``PermitRequestService._mint`` under its reserved id). A call presenting a
permit id whose row is not committed yet is indistinguishable from an
unknown permit, and the gateway treats it that way:

- denied ``permit_not_found`` before any reservation, debit, or dispatch;
- the governed idempotency record for that key is completed with the denial,
  so a same-key retry after activation replays the denial (no execution);
- a fresh key after activation executes exactly once.

Parking was rejected: there is no budget to reserve against until the row
exists, and holding a claim open would need a second owner for the
dispatch. See docs/retry-loop-alerting-and-caps.md.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import delete

from app.db.database import get_session_factory
from app.db.models import PermitModel
from app.schemas.billing import ServiceCategory
from app.services.service_registry import get_service_registry
from tests.test_mcp_trust_mode import (
    client,  # noqa: F401 - fixture
    _governed_idempotency_record_count,
    _jsonrpc_body,
    _tool_debit_count,
    strict_trust_mode,  # noqa: F401 - fixture
)
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet


async def _deactivate(permit_id: str) -> dict[str, Any]:
    """Remove the committed permit row, returning its column values."""
    async with get_session_factory()() as session:
        model = await session.get(PermitModel, permit_id)
        assert model is not None
        values = {c.name: getattr(model, c.name) for c in PermitModel.__table__.columns}
        await session.execute(
            delete(PermitModel).where(PermitModel.permit_id == permit_id)
        )
        await session.commit()
    return values


async def _activate(values: dict[str, Any]) -> None:
    async with get_session_factory()() as session:
        session.add(PermitModel(**values))
        await session.commit()


@pytest.mark.anyio
async def test_claim_racing_permit_activation_is_rejected_not_parked(
    client,  # noqa: F811
    clean_database,
    strict_trust_mode,  # noqa: F811
) -> None:
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    headers = provisioned["agent_headers"]
    tool_name = "claim-before-activation-tool"
    calls = {"count": 0}

    def counted_tool(message: str = "ok") -> dict:
        calls["count"] += 1
        return {"message": message}

    registry = get_service_registry()
    registry.register_local(
        service_id=tool_name,
        name="Claim Before Activation Tool",
        description="Pins claim-before-activation behaviour",
        category=ServiceCategory.AGENT_COMMS,
        func=counted_tool,
        credits_per_unit=2.0,
        unit_name="call",
    )
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=wallet_id,
            key_id=provisioned["key_id"],
            tool_name=tool_name,
        )
        permit_id = permit["permit_id"]
        # The caller holds the id; the row has not committed yet.
        row = await _deactivate(permit_id)

        early_key = "claim-before-activation-early"
        early = await client.post(
            "/mcp/messages",
            json=_jsonrpc_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                request_id="early",
                permit_id=permit_id,
                idempotency_key=early_key,
            ),
            headers=headers,
        )
        assert early.status_code == 200
        assert early.json()["error"]["message"] == "permit_not_found"
        assert calls["count"] == 0
        assert (
            await _tool_debit_count(
                client=client, wallet_id=wallet_id, headers=headers, tool_name=tool_name
            )
            == 0
        )
        # Rejected terminally, not parked: the record is complete, not pending.
        assert (
            await _governed_idempotency_record_count(
                wallet_id=wallet_id, idempotency_key=early_key
            )
            == 1
        )

        # Activation commits.
        await _activate(row)
        async with get_session_factory()() as session:
            committed = await session.get(PermitModel, permit_id)
            assert committed is not None
            assert committed.spent_credits == 0  # the early claim reserved nothing

        # Same key after activation: replays the rejection, does not execute.
        same_key = await client.post(
            "/mcp/messages",
            json=_jsonrpc_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                request_id="same-key-after-activation",
                permit_id=permit_id,
                idempotency_key=early_key,
            ),
            headers=headers,
        )
        assert same_key.json()["error"]["message"] == "permit_not_found"
        assert calls["count"] == 0

        # Fresh key after activation: executes exactly once.
        fresh = await client.post(
            "/mcp/messages",
            json=_jsonrpc_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                request_id="fresh-key-after-activation",
                permit_id=permit_id,
                idempotency_key="claim-before-activation-fresh",
            ),
            headers=headers,
        )
        payload = fresh.json()
        assert "error" not in payload, payload
        assert payload["result"]["isError"] is False
        assert calls["count"] == 1
        assert (
            await _tool_debit_count(
                client=client, wallet_id=wallet_id, headers=headers, tool_name=tool_name
            )
            == 1
        )
    finally:
        registry.unregister_local(tool_name)
