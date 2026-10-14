"""Optional provider-status reconciler for parked ``delivery_uncertain`` calls.

A ``delivery_uncertain`` attempt is already terminal and receipted: the debit
is retained and the permit reservation stays consumed (see
``PermitService._consumed_credits``). This worker asks the upstream, through
the operator-configured status endpoint (``UpstreamMcpStatusProbe``), what
actually happened to the forwarded invocation, and records the answer. It
never redispatches, never rewrites ``state``, and never touches the signed
receipt, which keeps verifying byte for byte.

Per sweep:

1. **Lease.** One short transaction selects due rows with
   ``SELECT ... FOR UPDATE SKIP LOCKED`` (a no-op on SQLite, where the
   conditional lease UPDATE alone decides ownership), stamps a random
   per-sweep owner and a lease expiry, and commits.
2. **Probe.** Network I/O happens with no database transaction open.
3. **Resolve.** Each claim is resolved in its own transaction by a
   conditional UPDATE that matches only while the row is still
   ``delivery_uncertain``, still unresolved, and still leased to this owner.
   A lost lease changes nothing.

Money moves only on an explicit, identifier-bound ``not_executed``
attestation received after the quiescence window (dispatch time + upstream
timeout allowance + clock-skew allowance) and only when the operator has
enabled ``UPSTREAM_RECONCILE_REFUND_ON_ATTESTED_NOT_EXECUTED``. A 404, an
unattested answer, a probe error, or age alone never refunds or releases
budget. The refund reuses the once-only gates of the live failure path
(deterministic refund entry, ``mark_debit_refunded``,
``release_dispatch_budget_once``), so the charge-once invariant holds.

Tools without a status endpoint are never leased: their calls stay in manual
review and only raise the age alert. Off by default
(``UPSTREAM_RECONCILE_WORKER_ENABLED``). Design:
``docs/delivery-uncertain-reconcile-worker.md``.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol, cast

from sqlalchemy import and_, func, literal, or_, select, update as sa_update
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import Settings, get_settings
from app.core.time import to_naive_utc, utc_now
from app.db.database import get_session_factory
from app.db.models import (
    ControlPlaneAuditEventModel,
    LedgerEntryModel,
    McpDispatchAttemptModel,
    RECONCILE_EXECUTED,
    RECONCILE_NOT_EXECUTED_REFUND_PENDING,
    RECONCILE_NOT_EXECUTED_REFUNDED,
    RECONCILE_NOT_EXECUTED_REVIEW,
    RECONCILE_TERMINAL_STATUSES,
    ReceiptModel,
)
from app.services.agent_money import AgentMoney, get_agent_money
from app.services.audit_log import record_audit_event
from app.services.mcp_dispatch_attempts import (
    McpDispatchAttemptService,
    dispatch_reconciliation_idle_seconds,
    get_mcp_dispatch_attempt_service,
)
from app.services.permits import PermitService, get_permit_service
from app.services.receipts import ReceiptService, get_receipt_service
from app.services.upstream_mcp import (
    UpstreamMcpConfiguration,
    UpstreamMcpStatusProbe,
    UpstreamStatusOutcome,
    extract_provider_request_id,
)

logger = logging.getLogger(__name__)

RESOLUTION_EVENT = "mcp_delivery_uncertain_provider_resolution"
RESOLUTION_EVENT_ID_PREFIX = "audit-ur-"
AGED_ALERT_EVENT = "mcp_delivery_uncertain_aged"
_DELIVERY_UNCERTAIN = "delivery_uncertain"

ProviderOutcome = UpstreamStatusOutcome


@dataclass(frozen=True)
class ProviderLookup:
    outcome: ProviderOutcome
    provider_request_id: str | None = None
    reason: str = "attested"


@dataclass(frozen=True)
class ParkedCall:
    """One leased ``delivery_uncertain`` attempt and its lookup handles."""

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
    receipt_id: str
    dispatch_time: datetime
    probe_count: int = 0
    reconcile_status: str | None = None
    ledger_entry_id: str | None = None


class ProviderStatusProbe(Protocol):
    """A status lookup scoped to exactly one configured tool and origin."""

    @property
    def public_tool_id(self) -> str: ...

    @property
    def upstream_origin(self) -> str: ...

    async def lookup(self, call: ParkedCall) -> ProviderLookup: ...


class UpstreamStatusEndpointProbe:
    """Adapts ``UpstreamMcpStatusProbe`` to the worker's probe protocol."""

    def __init__(self, probe: UpstreamMcpStatusProbe) -> None:
        self._probe = probe

    @property
    def public_tool_id(self) -> str:
        return self._probe.public_tool_id

    @property
    def upstream_origin(self) -> str:
        return self._probe.upstream_origin

    async def lookup(self, call: ParkedCall) -> ProviderLookup:
        answer = await self._probe.lookup(
            invocation_id=call.invocation_id,
            idempotency_key=call.forwarded_idempotency_key,
        )
        return ProviderLookup(
            answer.outcome, answer.provider_request_id, reason=answer.reason
        )


def build_configured_probe(settings: Settings) -> ProviderStatusProbe | None:
    """The configured status endpoint, or None (manual review only)."""
    if not settings.MCP_UPSTREAM_ENABLED or not settings.MCP_UPSTREAM_STATUS_URL:
        return None
    configuration = UpstreamMcpConfiguration.from_settings(settings)
    return UpstreamStatusEndpointProbe(UpstreamMcpStatusProbe(configuration))


@dataclass(frozen=True)
class ReconcileSweepResult:
    probed: int = 0
    resolved_executed: int = 0
    resolved_not_executed: int = 0
    refunded: int = 0
    deferred_quiescence: int = 0
    still_unknown: int = 0
    aged_alerts: int = 0
    probe_errors: int = 0
    lost_leases: int = 0
    audits_repaired: int = 0


def parse_backoff_seconds(value: str) -> tuple[int, ...]:
    steps = tuple(int(part) for part in value.split(",") if part.strip())
    if not steps or any(step <= 0 for step in steps):
        raise ValueError("upstream_reconcile_backoff_invalid")
    return steps


def quiescence_allowance_seconds(settings: Settings) -> int:
    """Upstream timeout allowance plus clock-skew allowance, in seconds.

    A configured allowance of 0 means the fixed rolling-deployment dispatch
    lifetime, which no worker's local settings can shrink. An explicit value
    is floored at this deployment's own connect + 3 x call timeout.
    """
    configured = settings.UPSTREAM_RECONCILE_UPSTREAM_TIMEOUT_SECONDS
    skew = settings.UPSTREAM_RECONCILE_CLOCK_SKEW_SECONDS
    if configured < 0 or skew < 0:
        raise ValueError("upstream_reconcile_quiescence_invalid")
    connect = settings.MCP_UPSTREAM_CONNECT_TIMEOUT_SECONDS
    call = settings.MCP_UPSTREAM_CALL_TIMEOUT_SECONDS
    if configured == 0:
        timeout = dispatch_reconciliation_idle_seconds(
            connect_timeout_seconds=connect, call_timeout_seconds=call
        )
    else:
        timeout = max(configured, math.ceil(connect + 3 * call))
    return timeout + skew


def resolution_event_id(attempt_id: str) -> str:
    return RESOLUTION_EVENT_ID_PREFIX + attempt_id


class DeliveryUncertainReconcileWorker:
    """Lease, probe outside any transaction, resolve under a conditional update.

    Backoff, probe count, lease, and resolution are durable on the attempt
    row, so restarts and concurrent replicas converge. Only the alert-once
    set is per process: a restart may re-alert an aged call once.
    """

    def __init__(
        self,
        probe: ProviderStatusProbe | None,
        *,
        backoff_seconds: Sequence[int] | None = None,
        alert_age_seconds: int | None = None,
        limit: int | None = None,
        lease_seconds: int | None = None,
        quiescence_seconds: int | None = None,
        refund_on_attested_not_executed: bool | None = None,
        now: Callable[[], datetime] = utc_now,
        money: AgentMoney | None = None,
        permit_service: PermitService | None = None,
        dispatch_service: McpDispatchAttemptService | None = None,
        receipt_service: ReceiptService | None = None,
    ) -> None:
        settings = get_settings()
        self._probe = probe
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
        self._lease = (
            lease_seconds
            if lease_seconds is not None
            else settings.UPSTREAM_RECONCILE_LEASE_SECONDS
        )
        if self._limit <= 0 or self._lease <= 0:
            raise ValueError("upstream_reconcile_limits_invalid")
        self._quiescence = (
            quiescence_seconds
            if quiescence_seconds is not None
            else quiescence_allowance_seconds(settings)
        )
        if self._quiescence < 0:
            raise ValueError("upstream_reconcile_quiescence_invalid")
        self._refund_enabled = (
            refund_on_attested_not_executed
            if refund_on_attested_not_executed is not None
            else settings.UPSTREAM_RECONCILE_REFUND_ON_ATTESTED_NOT_EXECUTED
        )
        self._now = now
        self._money = money or get_agent_money()
        self._permits = permit_service or get_permit_service()
        self._dispatch = dispatch_service or get_mcp_dispatch_attempt_service()
        self._receipts = receipt_service or get_receipt_service()
        self._alerted: set[str] = set()

    @classmethod
    def from_settings(cls) -> DeliveryUncertainReconcileWorker:
        return cls(build_configured_probe(get_settings()))

    def _clock(self) -> datetime:
        return to_naive_utc(self._now())

    async def run_once(self) -> ReconcileSweepResult:
        counts: dict[str, int] = dict.fromkeys(
            ReconcileSweepResult.__dataclass_fields__, 0
        )
        counts["audits_repaired"] = await self._repair_missing_resolution_audits()
        counts["aged_alerts"] = await self._alert_aged(self._clock())

        owner = uuid.uuid4().hex
        for call in await self.claim_due_calls(owner=owner):
            if call.reconcile_status == RECONCILE_NOT_EXECUTED_REFUND_PENDING:
                # A durable decision from an earlier sweep; finish it without
                # asking again.
                if await self._finish_refund(call, owner=owner):
                    counts["refunded"] += 1
                    counts["resolved_not_executed"] += 1
                continue
            await self._probe_and_resolve(call, owner=owner, counts=counts)
        return ReconcileSweepResult(**counts)

    async def _probe_and_resolve(
        self, call: ParkedCall, *, owner: str, counts: dict[str, int]
    ) -> None:
        if self._probe is None:  # pragma: no cover - nothing is leased then
            return
        valid, reason, _ = await self._receipts.verify_receipt(call.receipt_id)
        if not valid:
            # Fail closed: a resolution is only ever recorded against the
            # signed receipt the caller was given.
            counts["probe_errors"] += 1
            logger.error(
                "mcp_delivery_uncertain_receipt_invalid",
                extra={"dispatch_attempt_id": call.attempt_id, "reason": reason},
            )
            await self._reschedule(call, owner=owner, now=self._clock())
            return

        counts["probed"] += 1
        # No session is open here: the probe is network I/O only.
        try:
            lookup = await self._probe.lookup(call)
        except Exception as exc:
            counts["probe_errors"] += 1
            logger.warning(
                "mcp_delivery_uncertain_probe_failed",
                extra={
                    "dispatch_attempt_id": call.attempt_id,
                    "error": getattr(exc, "code", type(exc).__name__),
                },
            )
            await self._reschedule(call, owner=owner, now=self._clock())
            return

        now = self._clock()
        if lookup.outcome is ProviderOutcome.EXECUTED:
            if await self._resolve(
                call, owner=owner, status=RECONCILE_EXECUTED, now=now
            ):
                counts["resolved_executed"] += 1
                await self._record_resolution(call, RECONCILE_EXECUTED, lookup)
            else:
                counts["lost_leases"] += 1
            return

        if lookup.outcome is not ProviderOutcome.NOT_EXECUTED:
            counts["still_unknown"] += 1
            await self._reschedule(call, owner=owner, now=now)
            return

        deadline = self.quiescence_deadline(call)
        if now <= deadline:
            # The call may still be in flight upstream; an early "not
            # executed" can mean "not yet visible". Ask again after quiescence.
            counts["deferred_quiescence"] += 1
            await self._reschedule(
                call, owner=owner, now=now, not_before=deadline + timedelta(seconds=1)
            )
            return

        if not self._refund_enabled or call.ledger_entry_id is None:
            if await self._resolve(
                call, owner=owner, status=RECONCILE_NOT_EXECUTED_REVIEW, now=now
            ):
                counts["resolved_not_executed"] += 1
                await self._record_resolution(
                    call, RECONCILE_NOT_EXECUTED_REVIEW, lookup
                )
            else:
                counts["lost_leases"] += 1
            return

        # Commit the decision before any money moves, so a crash mid-refund
        # leaves a durable instruction the next sweep finishes, rather than a
        # refund nobody remembers deciding.
        if not await self._resolve(
            call,
            owner=owner,
            status=RECONCILE_NOT_EXECUTED_REFUND_PENDING,
            now=now,
            keep_lease=True,
        ):
            counts["lost_leases"] += 1
            return
        if await self._finish_refund(
            call, owner=owner, provider_request_id=lookup.provider_request_id
        ):
            counts["refunded"] += 1
            counts["resolved_not_executed"] += 1

    def quiescence_deadline(self, call: ParkedCall) -> datetime:
        return to_naive_utc(call.dispatch_time) + timedelta(seconds=self._quiescence)

    # --- leasing -----------------------------------------------------------

    def _due_conditions(self, now: datetime) -> list[ColumnElement[bool]]:
        attempt = McpDispatchAttemptModel
        lease_free = or_(
            cast(Any, attempt.reconcile_lease_expires_at).is_(None),
            cast(Any, attempt.reconcile_lease_expires_at) <= now,
        )
        pending = cast(
            ColumnElement[bool],
            attempt.reconcile_status == RECONCILE_NOT_EXECUTED_REFUND_PENDING,
        )
        branches: list[ColumnElement[bool]] = [pending]
        if self._probe is not None:
            first_due = now - timedelta(seconds=self._backoff[0])
            parked_at = func.coalesce(attempt.completed_at, attempt.updated_at)
            branches.append(
                and_(
                    cast(Any, attempt.reconcile_status).is_(None),
                    cast(
                        ColumnElement[bool],
                        attempt.public_tool_id == self._probe.public_tool_id,
                    ),
                    cast(
                        ColumnElement[bool],
                        attempt.upstream_origin == self._probe.upstream_origin,
                    ),
                    or_(
                        and_(
                            cast(Any, attempt.reconcile_next_probe_at).is_(None),
                            parked_at <= first_due,
                        ),
                        cast(Any, attempt.reconcile_next_probe_at) <= now,
                    ),
                )
            )
        return [
            cast(ColumnElement[bool], attempt.state == _DELIVERY_UNCERTAIN),
            lease_free,
            or_(*branches),
        ]

    def claim_statement(self, now: datetime) -> Any:
        """The leasing SELECT; exposed so tests can pin its locking clause."""
        attempt = McpDispatchAttemptModel
        return (
            select(cast(Any, attempt.attempt_id))
            .join(
                ReceiptModel,
                cast(
                    ColumnElement[bool],
                    ReceiptModel.dispatch_attempt_id == attempt.attempt_id,
                ),
            )
            .where(
                *self._due_conditions(now),
                # Only calls whose signed delivery_uncertain receipt exists:
                # an unfinalized row belongs to the crash reconciler first.
                cast(ColumnElement[bool], ReceiptModel.outcome == _DELIVERY_UNCERTAIN),
            )
            .order_by(
                func.coalesce(attempt.completed_at, attempt.updated_at).asc(),
                cast(Any, attempt.attempt_id).asc(),
            )
            .limit(self._limit)
            .with_for_update(skip_locked=True, of=attempt)
        )

    async def claim_due_calls(self, *, owner: str) -> list[ParkedCall]:
        """Lease due calls in one committed transaction; no network I/O."""
        now = self._clock()
        lease_until = now + timedelta(seconds=self._lease)
        attempt = McpDispatchAttemptModel
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                ids = list((await session.execute(self.claim_statement(now))).scalars())
                if not ids:
                    return []
                # The guarded UPDATE re-checks every condition, so on engines
                # without row locks (SQLite) two sweeps that selected the same
                # row cannot both own it.
                await session.execute(
                    sa_update(attempt)
                    .where(
                        cast(Any, attempt.attempt_id).in_(ids),
                        *self._due_conditions(now),
                    )
                    .values(
                        reconcile_lease_owner=owner,
                        reconcile_lease_expires_at=lease_until,
                    )
                    .execution_options(synchronize_session=False)
                )
        return await self._load_leased(owner)

    async def _load_leased(self, owner: str) -> list[ParkedCall]:
        attempt = McpDispatchAttemptModel
        stmt = (
            select(
                attempt,
                cast(Any, ReceiptModel.receipt_id),
                cast(Any, ReceiptModel.constraints_evaluated_json),
            )
            .join(
                ReceiptModel,
                cast(
                    ColumnElement[bool],
                    ReceiptModel.dispatch_attempt_id == attempt.attempt_id,
                ),
            )
            .where(cast(ColumnElement[bool], attempt.reconcile_lease_owner == owner))
            .order_by(func.coalesce(attempt.completed_at, attempt.updated_at).asc())
        )
        factory = get_session_factory()
        async with factory() as session:
            rows = (await session.execute(stmt)).all()
        return [
            _parked_call(row, receipt_id, constraints_json)
            for row, receipt_id, constraints_json in rows
        ]

    # --- resolution --------------------------------------------------------

    def _owned(self, call: ParkedCall, owner: str) -> list[ColumnElement[bool]]:
        attempt = McpDispatchAttemptModel
        return [
            cast(ColumnElement[bool], attempt.attempt_id == call.attempt_id),
            cast(ColumnElement[bool], attempt.state == _DELIVERY_UNCERTAIN),
            cast(ColumnElement[bool], attempt.reconcile_lease_owner == owner),
        ]

    async def _resolve(
        self,
        call: ParkedCall,
        *,
        owner: str,
        status: str,
        now: datetime,
        keep_lease: bool = False,
    ) -> bool:
        """Record a decision iff the row is still unresolved and leased to us."""
        attempt = McpDispatchAttemptModel
        values: dict[str, Any] = {
            "reconcile_status": status,
            "reconcile_probe_count": attempt.reconcile_probe_count + 1,
            "reconcile_next_probe_at": None,
        }
        if status in RECONCILE_TERMINAL_STATUSES:
            values["reconciled_at"] = now
        if not keep_lease:
            values["reconcile_lease_owner"] = None
            values["reconcile_lease_expires_at"] = None
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                result = await session.execute(
                    sa_update(attempt)
                    .where(
                        *self._owned(call, owner),
                        cast(Any, attempt.reconcile_status).is_(None),
                        cast(Any, attempt.reconcile_lease_expires_at) > now,
                    )
                    .values(**values)
                    .execution_options(synchronize_session=False)
                )
                return (cast(Any, result).rowcount or 0) == 1

    async def _reschedule(
        self,
        call: ParkedCall,
        *,
        owner: str,
        now: datetime,
        not_before: datetime | None = None,
    ) -> None:
        attempt = McpDispatchAttemptModel
        # The first probe waits backoff[0] from parking; after the n-th probe
        # (this one included) the next waits backoff[min(n, len - 1)].
        done = call.probe_count + 1
        step = self._backoff[min(done, len(self._backoff) - 1)]
        next_probe = now + timedelta(seconds=step)
        if not_before is not None and next_probe < not_before:
            next_probe = not_before
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    sa_update(attempt)
                    .where(
                        *self._owned(call, owner),
                        cast(Any, attempt.reconcile_status).is_(None),
                    )
                    .values(
                        reconcile_probe_count=attempt.reconcile_probe_count + 1,
                        reconcile_next_probe_at=next_probe,
                        reconcile_lease_owner=None,
                        reconcile_lease_expires_at=None,
                    )
                    .execution_options(synchronize_session=False)
                )

    async def _finish_refund(
        self,
        call: ParkedCall,
        *,
        owner: str,
        provider_request_id: str | None = None,
    ) -> bool:
        """Complete a durable not-executed decision; every step is once-only."""
        factory = get_session_factory()
        async with factory() as session:
            attempt = await session.get(McpDispatchAttemptModel, call.attempt_id)
            debit = (
                await session.get(LedgerEntryModel, attempt.ledger_entry_id)
                if attempt is not None and attempt.ledger_entry_id is not None
                else None
            )
        if (
            attempt is None
            or attempt.state != _DELIVERY_UNCERTAIN
            or attempt.reconcile_status != RECONCILE_NOT_EXECUTED_REFUND_PENDING
        ):
            return False
        if (
            debit is None
            or debit.wallet_id != attempt.wallet_id
            or debit.action != "debit"
            or debit.operation_key != attempt.idempotency_record_id
            or debit.amount >= Decimal("0")
        ):
            logger.error(
                "mcp_delivery_uncertain_refund_linkage_invalid",
                extra={"dispatch_attempt_id": attempt.attempt_id},
            )
            return False
        try:
            refund = await self._money.refund_charge(
                wallet_id=attempt.wallet_id,
                charge_entry_id=debit.entry_id,
                description=(
                    "Reconcile refunded attested not-executed upstream MCP "
                    f"dispatch {attempt.attempt_id}"
                ),
            )
            await self._dispatch.mark_debit_refunded(
                attempt_id=attempt.attempt_id, ledger_entry_id=debit.entry_id
            )
            await self._permits.release_dispatch_budget_once(
                attempt.attempt_id, is_system=True
            )
        except Exception as exc:
            # Leave the decision pending; the next sweep re-runs the same
            # idempotent steps once this lease expires.
            logger.warning(
                "mcp_delivery_uncertain_refund_incomplete",
                extra={
                    "dispatch_attempt_id": attempt.attempt_id,
                    "error": type(exc).__name__,
                },
            )
            return False

        now = self._clock()
        model = McpDispatchAttemptModel
        async with factory() as session:
            async with session.begin():
                result = await session.execute(
                    sa_update(model)
                    .where(
                        *self._owned(call, owner),
                        cast(
                            ColumnElement[bool],
                            model.reconcile_status
                            == RECONCILE_NOT_EXECUTED_REFUND_PENDING,
                        ),
                        cast(Any, model.debit_refunded_at).isnot(None),
                        cast(Any, model.budget_released_at).isnot(None),
                    )
                    .values(
                        reconcile_status=RECONCILE_NOT_EXECUTED_REFUNDED,
                        reconciled_at=now,
                        reconcile_lease_owner=None,
                        reconcile_lease_expires_at=None,
                    )
                    .execution_options(synchronize_session=False)
                )
                finalized = (cast(Any, result).rowcount or 0) == 1
        if finalized:
            await self._record_resolution(
                call,
                RECONCILE_NOT_EXECUTED_REFUNDED,
                ProviderLookup(ProviderOutcome.NOT_EXECUTED, provider_request_id),
                refund_ledger_entry_id=refund.entry_id,
            )
        return finalized

    async def _record_resolution(
        self,
        call: ParkedCall,
        status: str,
        lookup: ProviderLookup | None,
        *,
        refund_ledger_entry_id: str | None = None,
        repaired: bool = False,
    ) -> None:
        """One signed, hash-chained audit event per resolved attempt."""
        event_id = resolution_event_id(call.attempt_id)
        if await _audit_event_exists(event_id):
            return
        provider_outcome = (
            ProviderOutcome.EXECUTED
            if status == RECONCILE_EXECUTED
            else ProviderOutcome.NOT_EXECUTED
        )
        provider_request_id = extract_provider_request_id(
            {"id": lookup.provider_request_id if lookup else None}, "id"
        )
        refunded = status == RECONCILE_NOT_EXECUTED_REFUNDED
        metadata: dict[str, Any] = {
            "dispatch_attempt_id": call.attempt_id,
            "idempotency_record_id": call.invocation_id,
            "permit_id": call.permit_id,
            "receipt_id": call.receipt_id,
            "provider_outcome": provider_outcome.value,
            "provider_request_id": provider_request_id,
            "reconcile_status": status,
            # Explicit so an operator reading the event cannot assume money
            # moved when it did not.
            "budget_action": "refunded" if refunded else "none",
            "refund_candidate": status == RECONCILE_NOT_EXECUTED_REVIEW,
            "refund_ledger_entry_id": refund_ledger_entry_id,
            "quiescence_deadline": self.quiescence_deadline(call).isoformat(),
        }
        if repaired:
            metadata["repaired"] = True
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
                "reconcile_status": status,
                "budget_action": metadata["budget_action"],
            },
        )

    async def _repair_missing_resolution_audits(self) -> int:
        """Write the audit event for a resolution whose writer died after commit."""
        attempt = McpDispatchAttemptModel
        resolution = ControlPlaneAuditEventModel
        stmt = (
            select(
                attempt,
                cast(Any, ReceiptModel.receipt_id),
                cast(Any, ReceiptModel.constraints_evaluated_json),
            )
            .join(
                ReceiptModel,
                cast(
                    ColumnElement[bool],
                    ReceiptModel.dispatch_attempt_id == attempt.attempt_id,
                ),
            )
            .outerjoin(
                resolution,
                cast(
                    ColumnElement[bool],
                    resolution.event_id
                    == literal(RESOLUTION_EVENT_ID_PREFIX).concat(attempt.attempt_id),
                ),
            )
            .where(
                cast(Any, attempt.reconcile_status).in_(
                    sorted(RECONCILE_TERMINAL_STATUSES)
                ),
                cast(Any, resolution.event_id).is_(None),
            )
            .limit(self._limit)
        )
        factory = get_session_factory()
        async with factory() as session:
            rows = (await session.execute(stmt)).all()
        repaired = 0
        for row, receipt_id, constraints_json in rows:
            call = _parked_call(row, receipt_id, constraints_json)
            refund_entry = (
                f"refund-{row.ledger_entry_id}"
                if row.reconcile_status == RECONCILE_NOT_EXECUTED_REFUNDED
                else None
            )
            try:
                await self._record_resolution(
                    call,
                    row.reconcile_status,
                    None,
                    refund_ledger_entry_id=refund_entry,
                    repaired=True,
                )
                repaired += 1
            except Exception as exc:
                logger.warning(
                    "mcp_delivery_uncertain_audit_repair_failed",
                    extra={
                        "dispatch_attempt_id": row.attempt_id,
                        "error": type(exc).__name__,
                    },
                )
        return repaired

    async def _alert_aged(self, now: datetime) -> int:
        """Alert once per process for unresolved calls past the age threshold.

        Covers manual-review calls (no status endpoint) too. Alert only: the
        debit stays and the reservation stays consumed; ageing is never a
        reason to release budget.
        """
        attempt = McpDispatchAttemptModel
        cutoff = now - timedelta(seconds=self._alert_age)
        parked_at = func.coalesce(attempt.completed_at, attempt.updated_at)
        stmt = (
            select(attempt)
            .where(
                cast(ColumnElement[bool], attempt.state == _DELIVERY_UNCERTAIN),
                cast(Any, attempt.reconcile_status).is_(None),
                parked_at <= cutoff,
            )
            .order_by(parked_at.asc())
            .limit(self._limit)
        )
        factory = get_session_factory()
        async with factory() as session:
            rows = list((await session.execute(stmt)).scalars())
        alerts = 0
        for row in rows:
            if row.attempt_id in self._alerted:
                continue
            self._alerted.add(row.attempt_id)
            alerts += 1
            probeable = self._probe is not None and (
                row.public_tool_id == self._probe.public_tool_id
                and row.upstream_origin == self._probe.upstream_origin
            )
            logger.warning(
                AGED_ALERT_EVENT,
                extra={
                    "dispatch_attempt_id": row.attempt_id,
                    "public_tool_id": row.public_tool_id,
                    "upstream_origin": row.upstream_origin,
                    "age_seconds": int(
                        (
                            now - to_naive_utc(row.completed_at or row.updated_at)
                        ).total_seconds()
                    ),
                    "probes_done": row.reconcile_probe_count,
                    "manual_review": not probeable,
                },
            )
        return alerts


def _parked_call(
    attempt: McpDispatchAttemptModel,
    receipt_id: str,
    constraints_json: str | None,
) -> ParkedCall:
    parked_at = attempt.completed_at or attempt.updated_at
    return ParkedCall(
        attempt_id=attempt.attempt_id,
        wallet_id=attempt.wallet_id,
        permit_id=attempt.permit_id,
        public_tool_id=attempt.public_tool_id,
        upstream_origin=attempt.upstream_origin,
        invocation_id=attempt.idempotency_record_id,
        forwarded_idempotency_key=_forwarded_key(constraints_json),
        completed_at=parked_at,
        receipt_id=receipt_id,
        # Historical ``dispatched`` rows have no dispatch timestamp; the
        # terminal time is later than any send, so it is the safe fallback.
        dispatch_time=attempt.dispatched_at or parked_at,
        probe_count=attempt.reconcile_probe_count,
        reconcile_status=attempt.reconcile_status,
        ledger_entry_id=attempt.ledger_entry_id,
    )


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
    """Process-wide worker so the alert-once set survives between sweeps."""
    global _worker
    if _worker is None:
        _worker = DeliveryUncertainReconcileWorker.from_settings()
    return _worker
