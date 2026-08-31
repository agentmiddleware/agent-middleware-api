"""Two-process PostgreSQL fault-injection app for governed MCP acceptance tests.

This module is loaded only by the opt-in multiprocess stress harness.  It
registers one durable test tool and installs process-local gates around the
production commit boundaries.  No test-only hooks are imported by the normal
application.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi import Header, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import McpDispatchAttemptModel
from app.main import app
from app.routers import mcp as mcp_router
from app.schemas.billing import ServiceCategory
from app.services.agent_money import AgentMoney
from app.services.human_approval import HumanApprovalService
from app.services.idempotency import IdempotencyService, get_idempotency_service
from app.services.mcp_dispatch_attempts import McpDispatchAttemptService
from app.services.mcp_dispatch_reconciliation import (
    get_mcp_dispatch_reconciliation_service,
)
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
_CONTROL_TOKEN = os.environ.get("MCP_STRESS_CONTROL_TOKEN", "")
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
    original_flush = AsyncSession.flush
    original_begin_with_record = IdempotencyService.begin_with_record
    original_complete = IdempotencyService.complete
    original_mark_charged = IdempotencyService.mark_charged
    original_ensure_approval = HumanApprovalService.ensure_approval
    original_claim_dispatch = McpDispatchAttemptService.claim_dispatch
    original_complete_dispatch = McpDispatchAttemptService.complete
    original_authorize_and_reserve = PermitService.authorize_and_reserve
    original_charge = AgentMoney.charge
    original_create_receipt = ReceiptService.create_receipt
    original_audit = mcp_router._audit_mcp_invocation

    async def flush(self: AsyncSession, objects: Any = None) -> None:
        approval_attempt = next(
            (
                row
                for row in self.new
                if isinstance(row, McpDispatchAttemptModel)
                and row.approval_id is not None
            ),
            None,
        )
        await original_flush(self, objects)
        if approval_attempt is not None:
            # Approval UPDATE, permit UPDATE, and attempt INSERT have all
            # reached PostgreSQL in this still-uncommitted transaction.
            _fault(
                "after_approval_budget_attempt_flush_before_commit",
                approval_id=approval_attempt.approval_id,
                attempt_id=approval_attempt.attempt_id,
            )

    async def begin_with_record(
        self: IdempotencyService, *args: Any, **kwargs: Any
    ) -> Any:
        result = await original_begin_with_record(self, *args, **kwargs)
        if result.replay is None:
            _fault(
                "after_idempotency_begin",
                idempotency_key=kwargs.get("idempotency_key"),
                record_id=result.record_id,
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

    async def ensure_approval(
        self: HumanApprovalService, *args: Any, **kwargs: Any
    ) -> Any:
        result = await original_ensure_approval(self, *args, **kwargs)
        if (
            kwargs.get("consume_immediately") is False
            and getattr(result, "status", None) == "approved"
        ):
            _fault(
                "after_approval_before_prepare",
                approval_id=getattr(result, "approval_id", None),
            )
        return result

    async def claim_dispatch(
        self: McpDispatchAttemptService, *args: Any, **kwargs: Any
    ) -> Any:
        result = await original_claim_dispatch(self, *args, **kwargs)
        _fault(
            "after_dispatch_claim",
            attempt_id=getattr(result, "attempt_id", None),
        )
        return result

    async def complete_dispatch(
        self: McpDispatchAttemptService, *args: Any, **kwargs: Any
    ) -> Any:
        if kwargs.get("state") == "succeeded":
            _fault(
                "after_upstream_ack_before_terminal",
                attempt_id=kwargs.get("attempt_id"),
            )
        return await original_complete_dispatch(self, *args, **kwargs)

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

    IdempotencyService.begin_with_record = begin_with_record
    IdempotencyService.complete = complete
    IdempotencyService.mark_charged = mark_charged
    HumanApprovalService.ensure_approval = ensure_approval
    McpDispatchAttemptService.claim_dispatch = claim_dispatch
    McpDispatchAttemptService.complete = complete_dispatch
    PermitService.authorize_and_reserve = authorize_and_reserve
    AgentMoney.charge = charge
    ReceiptService.create_receipt = create_receipt
    mcp_router._audit_mcp_invocation = audit
    AsyncSession.flush = flush


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


def _authorize_control_request(provided_token: str | None) -> None:
    """Keep test-only process controls inaccessible without the run token."""
    if not _CONTROL_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="mcp_stress_control_not_configured",
        )
    if provided_token is None or not hmac.compare_digest(
        provided_token, _CONTROL_TOKEN
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="mcp_stress_control_denied",
        )


@app.get("/__stress/pid", include_in_schema=False)
async def stress_pid(
    control_token: str | None = Header(
        default=None,
        alias="X-MCP-Stress-Control",
    ),
) -> dict[str, Any]:
    _authorize_control_request(control_token)
    return {
        "pid": os.getpid(),
        "fault_point": _FAULT_POINT or None,
        "fault_action": _FAULT_ACTION,
    }


@app.post("/__stress/reconcile", include_in_schema=False)
async def stress_reconcile(
    idle_seconds: int = Query(default=0, ge=0),
    control_token: str | None = Header(
        default=None,
        alias="X-MCP-Stress-Control",
    ),
) -> dict[str, Any]:
    _authorize_control_request(control_token)
    dispatch = await get_mcp_dispatch_reconciliation_service().reconcile(
        idle_seconds=idle_seconds
    )
    repaired, needs_review = await get_idempotency_service().reconcile_stuck_records(
        idle_seconds=idle_seconds
    )
    permits_corrected = await get_permit_service().reconcile_budgets(
        idle_seconds=idle_seconds
    )
    return {
        "dispatch_prepared_finalized": dispatch.prepared_finalized,
        "dispatch_uncertain": dispatch.dispatched_uncertain,
        "dispatch_terminal_recovered": dispatch.terminal_recovered,
        "dispatch_idempotency_recovered": dispatch.idempotency_recovered,
        "dispatch_failed_attempt_ids": list(dispatch.failed_attempt_ids),
        "idempotency_repaired": repaired,
        "idempotency_needs_review": needs_review,
        "permit_budgets_corrected": permits_corrected,
    }
