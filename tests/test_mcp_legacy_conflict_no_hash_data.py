"""Legacy-record conflicts surface -32009 without comparable hashes.

docs/failure-semantics.md and docs/proposals/mcp-sep-idempotency-key.md say
``error.data`` is omitted when the key is held by a pre-canonical record:
its stored hash was computed over the raw transport payload, so it cannot be
compared with the canonical hash of the rejected request.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.routers.mcp import (
    GOVERNED_MCP_IDEMPOTENCY_ENDPOINT,
    IdempotencyKeyReusedError,
    _begin_governed_mcp_idempotency_scope,
)
from app.services.idempotency import IdempotencyConflictError

COMPLETED = SimpleNamespace(response_json={"ok": True})


class FakeIdem:
    def __init__(
        self,
        records: dict[str, Any] | None = None,
        *,
        insert_race_winner: Any = None,
    ) -> None:
        self.records = records or {}
        self.insert_race_winner = insert_race_winner

    async def get_record(self, *, endpoint: str, **_: Any) -> Any:
        return self.records.get(endpoint)

    async def begin_with_record(self, *, endpoint: str, **_: Any) -> Any:
        assert endpoint == GOVERNED_MCP_IDEMPOTENCY_ENDPOINT
        raise IntegrityError("insert", {}, Exception("unique violation"))

    async def get_governed_mcp_record(self, **_: Any) -> Any:
        return self.insert_race_winner


async def _begin(idem: FakeIdem) -> None:
    await _begin_governed_mcp_idempotency_scope(
        idem=idem,
        wallet_id="wallet-1",
        idempotency_key="key-1",
        tool_name="echo",
        endpoint="/mcp/messages",
        logical_request_payload={"tool": "echo"},
        legacy_request_payload=None,
        operation_kind="mcp_tool_call",
    )


def _assert_hashless(conflict: IdempotencyConflictError) -> None:
    assert str(conflict) == "idempotency_key_reused"
    assert conflict.as_error_data() is None
    # The JSON-RPC handlers attach ``data`` only when this is truthy.
    assert IdempotencyKeyReusedError(conflict).error_data is None


@pytest.mark.anyio
async def test_completed_record_from_other_transport_conflicts_without_hashes():
    idem = FakeIdem({"/mcp/tools/echo/invoke": COMPLETED})
    with pytest.raises(IdempotencyConflictError) as exc_info:
        await _begin(idem)
    _assert_hashless(exc_info.value)


@pytest.mark.anyio
async def test_lost_insert_race_to_legacy_worker_conflicts_without_hashes():
    idem = FakeIdem(insert_race_winner=COMPLETED)
    with pytest.raises(IdempotencyConflictError) as exc_info:
        await _begin(idem)
    _assert_hashless(exc_info.value)
