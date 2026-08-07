"""Two-process PostgreSQL fault-injection app for governed MCP acceptance tests.

This module is loaded only by the opt-in multiprocess stress harness.  It
registers one durable test tool and installs process-local gates around the
production commit boundaries.  No test-only hooks are imported by the normal
application.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi import Query
from sqlalchemy import text

from app.main import app
from app.routers import mcp as mcp_router
from app.schemas.billing import ServiceCategory
from app.services.agent_money import AgentMoney
from app.services.idempotency import IdempotencyService, get_idempotency_service
from app.services.permits import PermitService, get_permit_service
from app.services.receipts import ReceiptService
from app.services.service_registry import get_service_registry


_FAULT_POINT = os.environ.get("MCP_STRESS_FAULT_POINT", "")
_FAULT_ACTION = os.environ.get("MCP_STRESS_FAULT_ACTION", "pause")
_FAULT_REPEAT = os.environ.get("MCP_STRESS_FAULT_REPEAT", "once")
_MARKER_PATH = Path(os.environ.get("MCP_STRESS_MARKER_PATH", "/tmp/mcp-stress.marker"))
_RELEASE_PATH = Path(
    os.environ.get("MCP_STRESS_RELEASE_PATH", "/tmp/mcp-stress.release")
)
_fault_count = 0


def _fault(point: str, **context: Any) -> None:
    """Trigger the configured gate after a production method returns.

    ``pause`` writes a durable marker and blocks until the parent creates the
    release file (or kills this process). ``raise`` simulates a commit whose
    acknowledgement was lost after the durable write landed.
    """

    global _fault_count
    if _FAULT_POINT != point:
        return
    if _FAULT_REPEAT != "always" and _fault_count:
        return

    _fault_count += 1
    _MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    marker = {
        "point": point,
        "action": _FAULT_ACTION,
        "count": _fault_count,
        "pid": os.getpid(),
        "context": context,
        "written_at_unix": time.time(),
    }
    _MARKER_PATH.write_text(json.dumps(marker, sort_keys=True), encoding="utf-8")

    if _FAULT_ACTION == "raise":
        raise RuntimeError(f"mcp_stress_lost_commit_ack:{point}:{_fault_count}")
    if _FAULT_ACTION != "pause":
        raise RuntimeError(f"Unsupported MCP_STRESS_FAULT_ACTION={_FAULT_ACTION!r}")

    while not _RELEASE_PATH.exists():
        time.sleep(0.01)


def _install_fault_wrappers() -> None:
    original_begin = IdempotencyService.begin
    original_complete = IdempotencyService.complete
    original_mark_charged = IdempotencyService.mark_charged
    original_authorize_and_reserve = PermitService.authorize_and_reserve
    original_charge = AgentMoney.charge
    original_create_receipt = ReceiptService.create_receipt
    original_audit = mcp_router._audit_mcp_invocation

    async def begin(self: IdempotencyService, *args: Any, **kwargs: Any) -> Any:
        result = await original_begin(self, *args, **kwargs)
        if result is None:
            _fault(
                "after_idempotency_begin", idempotency_key=kwargs.get("idempotency_key")
            )
        return result

    async def complete(self: IdempotencyService, *args: Any, **kwargs: Any) -> Any:
        result = await original_complete(self, *args, **kwargs)
        _fault(
            "after_idempotency_complete", idempotency_key=kwargs.get("idempotency_key")
        )
        return result

    async def mark_charged(self: IdempotencyService, *args: Any, **kwargs: Any) -> Any:
        result = await original_mark_charged(self, *args, **kwargs)
        _fault(
            "after_mark_charged",
            idempotency_key=kwargs.get("idempotency_key"),
            ledger_entry_id=kwargs.get("ledger_entry_id"),
        )
        return result

    async def authorize_and_reserve(
        self: PermitService, *args: Any, **kwargs: Any
    ) -> Any:
        _fault("before_permit_reserve", permit_id=kwargs.get("permit_id"))
        result = await original_authorize_and_reserve(self, *args, **kwargs)
        if getattr(result, "allowed", False):
            _fault("after_permit_reserve", permit_id=kwargs.get("permit_id"))
        return result

    async def charge(self: AgentMoney, *args: Any, **kwargs: Any) -> Any:
        result = await original_charge(self, *args, **kwargs)
        entry_id = getattr(result, "entry_id", None)
        if entry_id:
            _fault(
                "after_debit_commit",
                wallet_id=kwargs.get("wallet_id"),
                ledger_entry_id=entry_id,
            )
        return result

    async def create_receipt(self: ReceiptService, *args: Any, **kwargs: Any) -> Any:
        _fault(
            "before_receipt_commit",
            permit_id=kwargs.get("permit_id"),
            ledger_entry_id=kwargs.get("ledger_entry_id"),
        )
        result = await original_create_receipt(self, *args, **kwargs)
        _fault(
            "after_receipt_commit",
            permit_id=kwargs.get("permit_id"),
            ledger_entry_id=kwargs.get("ledger_entry_id"),
            receipt_id=getattr(result, "receipt_id", None),
        )
        return result

    async def audit(*args: Any, **kwargs: Any) -> Any:
        result = await original_audit(*args, **kwargs)
        _fault("after_audit_commit", audit_event_id=getattr(result, "event_id", None))
        return result

    IdempotencyService.begin = begin
    IdempotencyService.complete = complete
    IdempotencyService.mark_charged = mark_charged
    PermitService.authorize_and_reserve = authorize_and_reserve
    AgentMoney.charge = charge
    ReceiptService.create_receipt = create_receipt
    mcp_router._audit_mcp_invocation = audit


async def _stress_tool(
    call_token: str,
    mode: str = "success",
    delay_ms: int = 0,
) -> dict[str, Any]:
    """Persist a side effect before returning or raising.

    The table intentionally permits duplicate ``call_token`` values: duplicate
    execution must be observed and counted, not hidden behind another unique
    constraint.
    """

    from app.db.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        row = await session.execute(
            text(
                """
                INSERT INTO mcp_stress_tool_executions
                    (call_token, mode, worker_pid)
                VALUES (:call_token, :mode, :worker_pid)
                RETURNING execution_id
                """
            ),
            {
                "call_token": call_token,
                "mode": mode,
                "worker_pid": os.getpid(),
            },
        )
        execution_id = int(row.scalar_one())
        await session.commit()

    _fault(
        "after_tool_side_effect",
        call_token=call_token,
        execution_id=execution_id,
    )
    if delay_ms:
        await asyncio.sleep(delay_ms / 1000)
    if mode == "fail":
        raise RuntimeError("stress_tool_requested_failure")
    return {
        "call_token": call_token,
        "execution_id": execution_id,
        "worker_pid": os.getpid(),
    }


_install_fault_wrappers()
get_service_registry().register_local(
    service_id="stress-governed-tool",
    name="Stress Governed Tool",
    description="Durable side-effect tool used only by the opt-in PG harness",
    category=ServiceCategory.AGENT_COMMS,
    func=_stress_tool,
    credits_per_unit=2.0,
    unit_name="call",
    require_permit=True,
)


@app.get("/__stress/pid", include_in_schema=False)
async def stress_pid() -> dict[str, Any]:
    return {
        "pid": os.getpid(),
        "fault_point": _FAULT_POINT or None,
        "fault_action": _FAULT_ACTION,
    }


@app.post("/__stress/reconcile", include_in_schema=False)
async def stress_reconcile(
    idle_seconds: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    repaired, needs_review = await get_idempotency_service().reconcile_stuck_records(
        idle_seconds=idle_seconds
    )
    permits_corrected = await get_permit_service().reconcile_budgets(
        idle_seconds=idle_seconds
    )
    return {
        "idempotency_repaired": repaired,
        "idempotency_needs_review": needs_review,
        "permit_budgets_corrected": permits_corrected,
    }
