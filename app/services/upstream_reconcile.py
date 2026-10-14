"""Optional provider-status reconcile worker for parked ``delivery_uncertain`` calls.

A ``delivery_uncertain`` attempt is already terminal and receipted: the debit
is retained and the permit reservation stays consumed (see
``PermitService._sum_permit_charges``). This worker never changes that. It
asks the upstream provider, by the forwarded idempotency key, what actually
happened, and records the answer as one deterministic audit event per
attempt. It does not redispatch, refund, release budget, or mutate the
attempt or its signed receipt; money movement on a confirmed
``not_executed`` stays an operator decision.

Off by default (``UPSTREAM_RECONCILE_WORKER_ENABLED``). MCP has no standard
status-lookup method, so the default probe answers ``unknown`` and the worker
then only provides the age alert. A deployment that has a provider lookup
plugs in a ``ProviderStatusProbe``. Design and remaining work:
``docs/delivery-uncertain-reconcile-worker.md``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Protocol, cast

from sqlalchemy import literal, select
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import get_settings
from app.core.time import to_naive_utc, utc_now
from app.db.database import get_session_factory
from app.db.models import (
    ControlPlaneAuditEventModel,
    McpDispatchAttemptModel,
    ReceiptModel,
)
from app.services.audit_log import record_audit_event
from app.services.upstream_mcp import extract_provider_request_id

logger = logging.getLogger(__name__)

RESOLUTION_EVENT = "mcp_delivery_uncertain_provider_resolution"
RESOLUTION_EVENT_ID_PREFIX = "audit-ur-"
AGED_ALERT_EVENT = "mcp_delivery_uncertain_aged"


class ProviderOutcome(str, Enum):
    EXECUTED = "executed"
    NOT_EXECUTED = "not_executed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProviderLookup:
    outcome: ProviderOutcome
    provider_request_id: str | None = None


@dataclass(frozen=True)
class ParkedCall:
    """One unresolved ``delivery_uncertain`` attempt and its lookup handles."""

    attempt_id: str
    wallet_id: str
    permit_id: str
    public_tool_id: str
    upstream_origin: str
    # Forwarded as ``io.agentmiddleware/invocation_id``.
    invocation_id: str
    # Forwarded as ``io.agentmiddleware/idempotency_key``; read from the
    # signed receipt, None for receipts minted before that field existed or
    # by crash reconciliation.
    forwarded_idempotency_key: str | None
    completed_at: datetime


class ProviderStatusProbe(Protocol):
    async def lookup(self, call: ParkedCall) -> ProviderLookup: ...


class NullProviderStatusProbe:
    """Default probe: MCP defines no status lookup, so the answer is unknown."""

    async def lookup(self, call: ParkedCall) -> ProviderLookup:
        return ProviderLookup(ProviderOutcome.UNKNOWN)


@dataclass(frozen=True)
class ReconcileSweepResult:
    probed: int = 0
    resolved_executed: int = 0
    resolved_not_executed: int = 0
    still_unknown: int = 0
    aged_alerts: int = 0
    probe_errors: int = 0


def parse_backoff_seconds(value: str) -> tuple[int, ...]:
    steps = tuple(int(part) for part in value.split(",") if part.strip())
    if not steps or any(step <= 0 for step in steps):
        raise ValueError("upstream_reconcile_backoff_invalid")
    return steps


def resolution_event_id(attempt_id: str) -> str:
    return RESOLUTION_EVENT_ID_PREFIX + attempt_id


class DeliveryUncertainReconcileWorker:
    """Poll a provider probe on a backoff; alert on age; never move money.

    Backoff and alert-once state is per process. A restart probes due calls
    again and may re-alert once; resolution itself is durable and
    idempotent (deterministic audit event id).
    """

    def __init__(
        self,
        probe: ProviderStatusProbe | None = None,
        *,
        backoff_seconds: Sequence[int] | None = None,
        alert_age_seconds: int | None = None,
        limit: int | None = None,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        settings = get_settings()
        self._probe = probe or NullProviderStatusProbe()
        self._backoff = tuple(
            backoff_seconds
            if backoff_seconds is not None
            else parse_backoff_seconds(settings.UPSTREAM_RECONCILE_BACKOFF_SECONDS)
        )
        if not self._backoff or any(step <= 0 for step in self._backoff):
            raise ValueError("upstream_reconcile_backoff_invalid")
        self._alert_age = (
            alert_age_seconds
            if alert_age_seconds is not None
            else settings.UPSTREAM_RECONCILE_ALERT_AGE_SECONDS
        )
        self._limit = (
            limit if limit is not None else settings.UPSTREAM_RECONCILE_BATCH_LIMIT
        )
        self._now = now
        self._probes_done: dict[str, int] = {}
        self._next_due: dict[str, datetime] = {}
        self._alerted: set[str] = set()

    async def run_once(self) -> ReconcileSweepResult:
        now = to_naive_utc(self._now())
        probed = executed = not_executed = unknown = alerts = errors = 0
        for call in await self.list_parked_calls(limit=self._limit):
            completed_at = to_naive_utc(call.completed_at)
            age_seconds = (now - completed_at).total_seconds()

            due_at = self._next_due.get(call.attempt_id)
            if due_at is None:
                due_at = completed_at + timedelta(seconds=self._backoff[0])
            if now >= due_at:
                probed += 1
                outcome = await self._probe_once(call, now=now)
                if outcome is None:
                    errors += 1
                elif outcome is ProviderOutcome.EXECUTED:
                    executed += 1
                    continue
                elif outcome is ProviderOutcome.NOT_EXECUTED:
                    not_executed += 1
                    continue
                else:
                    unknown += 1

            if age_seconds >= self._alert_age and call.attempt_id not in self._alerted:
                self._alerted.add(call.attempt_id)
                alerts += 1
                # Alert only. The debit stays and the permit reservation stays
                # consumed; ageing is never a reason to release budget.
                logger.warning(
                    AGED_ALERT_EVENT,
                    extra={
                        "dispatch_attempt_id": call.attempt_id,
                        "public_tool_id": call.public_tool_id,
                        "upstream_origin": call.upstream_origin,
                        "age_seconds": int(age_seconds),
                        "probes_done": self._probes_done.get(call.attempt_id, 0),
                    },
                )
        return ReconcileSweepResult(
            probed=probed,
            resolved_executed=executed,
            resolved_not_executed=not_executed,
            still_unknown=unknown,
            aged_alerts=alerts,
            probe_errors=errors,
        )

    async def _probe_once(
        self, call: ParkedCall, *, now: datetime
    ) -> ProviderOutcome | None:
        done = self._probes_done.get(call.attempt_id, 0) + 1
        self._probes_done[call.attempt_id] = done
        self._next_due[call.attempt_id] = now + timedelta(
            seconds=self._backoff[min(done, len(self._backoff) - 1)]
        )
        try:
            lookup = await self._probe.lookup(call)
        except Exception as exc:
            logger.warning(
                "mcp_delivery_uncertain_probe_failed",
                extra={
                    "dispatch_attempt_id": call.attempt_id,
                    "error": type(exc).__name__,
                },
            )
            return None
        if lookup.outcome is ProviderOutcome.UNKNOWN:
            return ProviderOutcome.UNKNOWN
        await self._record_resolution(call, lookup)
        self._forget(call.attempt_id)
        return lookup.outcome

    async def _record_resolution(
        self, call: ParkedCall, lookup: ProviderLookup
    ) -> None:
        event_id = resolution_event_id(call.attempt_id)
        if await _audit_event_exists(event_id):
            return
        provider_request_id = extract_provider_request_id(
            {"id": lookup.provider_request_id}, "id"
        )
        metadata: dict[str, Any] = {
            "dispatch_attempt_id": call.attempt_id,
            "idempotency_record_id": call.invocation_id,
            "permit_id": call.permit_id,
            "provider_outcome": lookup.outcome.value,
            "provider_request_id": provider_request_id,
            # Explicit so an operator reading the event cannot assume money
            # moved: a not_executed answer is a refund candidate, not a refund.
            "budget_action": "none",
            "refund_candidate": lookup.outcome is ProviderOutcome.NOT_EXECUTED,
        }
        try:
            await record_audit_event(
                event=RESOLUTION_EVENT,
                event_id=event_id,
                wallet_id=call.wallet_id,
                tool=call.public_tool_id,
                ok=True,
                metadata=metadata,
            )
        except Exception:
            # A concurrent worker may have written the same deterministic id.
            if not await _audit_event_exists(event_id):
                raise
        logger.warning(
            "mcp_delivery_uncertain_resolved",
            extra={
                "dispatch_attempt_id": call.attempt_id,
                "provider_outcome": lookup.outcome.value,
                "refund_candidate": metadata["refund_candidate"],
            },
        )

    def _forget(self, attempt_id: str) -> None:
        self._probes_done.pop(attempt_id, None)
        self._next_due.pop(attempt_id, None)
        self._alerted.discard(attempt_id)

    @staticmethod
    async def list_parked_calls(*, limit: int) -> list[ParkedCall]:
        """Oldest unresolved ``delivery_uncertain`` attempts, bounded."""
        resolution = ControlPlaneAuditEventModel
        stmt = (
            select(
                McpDispatchAttemptModel,
                cast(Any, ReceiptModel.constraints_evaluated_json),
            )
            .outerjoin(
                ReceiptModel,
                cast(
                    ColumnElement[bool],
                    ReceiptModel.dispatch_attempt_id
                    == McpDispatchAttemptModel.attempt_id,
                ),
            )
            .outerjoin(
                resolution,
                cast(
                    ColumnElement[bool],
                    resolution.event_id
                    == literal(RESOLUTION_EVENT_ID_PREFIX).concat(
                        McpDispatchAttemptModel.attempt_id
                    ),
                ),
            )
            .where(
                cast(
                    ColumnElement[bool],
                    McpDispatchAttemptModel.state == "delivery_uncertain",
                ),
                cast(Any, resolution.event_id).is_(None),
            )
            .order_by(cast(Any, McpDispatchAttemptModel.completed_at).asc())
            .limit(limit)
        )
        factory = get_session_factory()
        async with factory() as session:
            rows = (await session.execute(stmt)).all()
        calls: list[ParkedCall] = []
        for attempt, constraints_json in rows:
            calls.append(
                ParkedCall(
                    attempt_id=attempt.attempt_id,
                    wallet_id=attempt.wallet_id,
                    permit_id=attempt.permit_id,
                    public_tool_id=attempt.public_tool_id,
                    upstream_origin=attempt.upstream_origin,
                    invocation_id=attempt.idempotency_record_id,
                    forwarded_idempotency_key=_forwarded_key(constraints_json),
                    completed_at=attempt.completed_at or attempt.updated_at,
                )
            )
        return calls


def _forwarded_key(constraints_json: str | None) -> str | None:
    try:
        decoded = json.loads(constraints_json or "{}")
    except json.JSONDecodeError:
        return None
    evidence = decoded.get("upstream_dispatch") if isinstance(decoded, dict) else None
    if not isinstance(evidence, dict):
        return None
    value = evidence.get("forwarded_idempotency_key")
    return value if type(value) is str and value else None


async def _audit_event_exists(event_id: str) -> bool:
    factory = get_session_factory()
    async with factory() as session:
        return await session.get(ControlPlaneAuditEventModel, event_id) is not None


_worker: DeliveryUncertainReconcileWorker | None = None


def get_delivery_uncertain_reconcile_worker() -> DeliveryUncertainReconcileWorker:
    """Process-wide worker so backoff/alert-once state survives between sweeps."""
    global _worker
    if _worker is None:
        _worker = DeliveryUncertainReconcileWorker()
    return _worker
