"""Read narrow, wallet-scoped operation evidence in one authorized snapshot.

The caller owns the read-only repeatable-read transaction.  No source read is
allowed until auth has checked the exact Scope/session/transaction binding.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    and_,
    exists,
    false,
    func,
    inspect as sa_inspect,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.core.time import to_naive_utc
from app.db.models import (
    HumanApprovalModel,
    IdempotencyRecordModel,
    LedgerEntryModel,
    McpDispatchAttemptModel,
    PermitModel,
    PermitRequestModel,
    ReceiptModel,
)
from app.services.operation_insights.contracts import (
    Coverage,
    EffectState,
    Evidence,
    EvidenceBatch,
    EvidenceRef,
    EvidenceStateFacts,
    GatewayOutcome,
    Limits,
    Scope,
    Snapshot,
    SourceCoverage,
    StageTimestamp,
    UnknownWalletCount,
    Window,
    RequestDisposition,
)


_SAFE_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_SAFE_REASON = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_GOVERNED_ENDPOINTS = ("/mcp/invoke", "/mcp/messages", "/mcp/action/v1")
_SOURCE_NAMES = (
    "insight_event",
    "idempotency",
    "dispatch",
    "audit",
    "ledger",
    "receipt",
    "permit",
    "permit_request",
    "approval",
    "refund",
)
_EVENTS = Table(
    "operation_insight_events",
    MetaData(),
    Column("event_id", String, primary_key=True),
    Column("kind", String),
    Column("request_id", String),
    Column("attempt_id", String),
    Column("logical_operation_id", String),
    Column("wallet_id", String),
    Column("ownership_epoch_id", String),
    Column("original_operation_anchor_id", String),
    Column("request_disposition", String),
    Column("tool", String),
    Column("reason_code", String),
    Column("gateway_outcome", String),
    Column("effect_state", String),
    Column("http_status_code", String),
    Column("occurred_at", DateTime),
    Column("ingested_at", DateTime),
    Column("duplicate_conflict_at", DateTime),
    Column("environment", String),
    Column("server_release", String),
    Column("deployment", String),
    Column("client_version", String),
)
_DISPOSITIONS = frozenset(
    (
        "execution_intent",
        "same_key_replay",
        "status_read",
        "non_execution_read",
        "unknown",
    )
)
_GATEWAY_OUTCOMES = frozenset(
    ("succeeded", "failed", "denied", "unknown", "conflicting")
)
_EFFECT_STATES = frozenset(("confirmed", "no_effect_proven", "unknown", "conflicting"))
_DISPATCH_STATES = frozenset(
    (
        "prepared",
        "dispatched",
        "dispatch_claimed",
        "succeeded",
        "returned_error",
        "delivery_uncertain",
        "response_rejected",
        "unknown",
        "conflicting",
    )
)


def _bound(scope: Scope, session: AsyncSession) -> None:
    # Import at call time so this module can be tested before auth is merged.
    from app.services.operation_insights.auth import assert_scope_bound

    assert_scope_bound(scope, session)


def _aware(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _safe(value: str | None) -> str | None:
    return value if value is not None and _SAFE_ID.fullmatch(value) else None


def _safe_reason(value: str | None) -> str | None:
    return value if value is not None and _SAFE_REASON.fullmatch(value) else None


def _known(value: str | None, allowed: frozenset[str]) -> str | None:
    return value if value in allowed else None


def _epoch_filter(scope: Scope, wallet_column: Any, anchor_column: Any) -> Any:
    """Apply exact wallet and granted historical interval inside the SQL read."""
    clauses = [
        and_(
            wallet_column == epoch.wallet_id,
            anchor_column >= to_naive_utc(epoch.evidence_from),
            anchor_column < to_naive_utc(epoch.evidence_until),
        )
        for epoch in scope.authorized_ownership_epochs
    ]
    return or_(*clauses) if clauses else false()


def _event_epoch_filter(scope: Scope, event_table: Any) -> Any:
    clauses = [
        and_(
            event_table.c.wallet_id == epoch.wallet_id,
            event_table.c.occurred_at >= to_naive_utc(epoch.evidence_from),
            event_table.c.occurred_at < to_naive_utc(epoch.evidence_until),
            or_(
                event_table.c.ownership_epoch_id.is_(None),
                event_table.c.ownership_epoch_id == epoch.ownership_epoch_id,
            ),
        )
        for epoch in scope.authorized_ownership_epochs
    ]
    return or_(*clauses) if clauses else false()


def _ingress_anchor_filter(scope: Scope, event_table: Any) -> Any:
    """A replay/read can inherit only a proven original epoch, never its own time."""
    original = _EVENTS.alias("original_anchor_event")
    i = IdempotencyRecordModel
    clauses = []
    for epoch in scope.authorized_ownership_epochs:
        in_epoch = lambda column: and_(
            column >= to_naive_utc(epoch.evidence_from),
            column < to_naive_utc(epoch.evidence_until),
        )
        matching_idem = exists(
            select(1)
            .select_from(i)
            .where(
                col(i.record_id) == event_table.c.original_operation_anchor_id,
                col(i.wallet_id) == epoch.wallet_id,
                in_epoch(col(i.created_at)),
                or_(
                    col(i.endpoint).in_(_GOVERNED_ENDPOINTS),
                    col(i.endpoint).like("/mcp/tools/%/invoke"),
                ),
            )
        )
        matching_original_event = exists(
            select(1)
            .select_from(original)
            .where(
                original.c.event_id == event_table.c.original_operation_anchor_id,
                original.c.original_operation_anchor_id == original.c.event_id,
                original.c.kind == "ingress",
                original.c.request_disposition == "execution_intent",
                original.c.wallet_id == epoch.wallet_id,
                in_epoch(original.c.occurred_at),
                original.c.ingested_at.is_not(None),
                original.c.duplicate_conflict_at.is_(None),
            )
        )
        clauses.append(
            and_(
                event_table.c.wallet_id == epoch.wallet_id,
                in_epoch(event_table.c.occurred_at),
                or_(
                    event_table.c.ownership_epoch_id.is_(None),
                    event_table.c.ownership_epoch_id == epoch.ownership_epoch_id,
                ),
                or_(
                    and_(
                        event_table.c.request_disposition == "execution_intent",
                        or_(
                            event_table.c.original_operation_anchor_id
                            == event_table.c.event_id,
                            matching_idem,
                        ),
                    ),
                    and_(
                        event_table.c.request_disposition != "execution_intent",
                        or_(matching_idem, matching_original_event),
                    ),
                ),
            )
        )
    return or_(*clauses) if clauses else false()


def _epoch_for(scope: Scope, wallet_id: str, anchor: datetime) -> str | None:
    instant = _aware(anchor)
    epochs = [
        epoch.ownership_epoch_id
        for epoch in scope.authorized_ownership_epochs
        if epoch.wallet_id == wallet_id
        and epoch.evidence_from <= instant < epoch.evidence_until
    ]
    return epochs[0] if len(epochs) == 1 else None


async def _has_events(session: AsyncSession) -> bool:
    connection = await session.connection()
    return bool(
        await connection.run_sync(
            lambda sync_connection: sa_inspect(sync_connection).has_table(
                "operation_insight_events"
            )
        )
    )


async def _keyset(
    session: AsyncSession,
    statement: Any,
    timestamp_column: Any,
    id_column: Any,
    page_size: int,
    *,
    deadline: float,
):
    """Traverse all equal-time rows, including nullable-time rows, exactly once."""
    cursor: tuple[datetime | None, str] | None = None
    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError("insight_read_budget_exceeded")
        page_stmt = statement
        if cursor is not None:
            last_time, last_id = cursor
            if last_time is None:
                page_stmt = page_stmt.where(
                    or_(
                        and_(timestamp_column.is_(None), id_column > last_id),
                        timestamp_column.is_not(None),
                    )
                )
            else:
                page_stmt = page_stmt.where(
                    or_(
                        timestamp_column > last_time,
                        and_(timestamp_column == last_time, id_column > last_id),
                    )
                )
        result = await session.execute(
            page_stmt.order_by(
                timestamp_column.asc().nullsfirst(), id_column.asc()
            ).limit(page_size)
        )
        rows = result.mappings().all()
        if not rows:
            return
        yield rows
        tail = rows[-1]
        cursor = (tail["page_time"], tail["page_id"])
        if len(rows) < page_size:
            return


def _event_evidence(record: Any, epoch_id: str | None) -> Evidence | None:
    source_id = _safe(record["page_id"])
    wallet_id = _safe(record["wallet_id"])
    anchor_id = _safe(record["original_operation_anchor_id"])
    request_id = _safe(record["request_id"])
    kind = record["kind"]
    occurred_at = record["page_time"]
    if (
        source_id is None
        or wallet_id is None
        or anchor_id is None
        or epoch_id is None
        or occurred_at is None
        or kind not in ("ingress", "attempt", "terminal")
        or (
            record["ownership_epoch_id"] is not None
            and record["ownership_epoch_id"] != epoch_id
        )
    ):
        return None
    disposition = _known(record["request_disposition"], _DISPOSITIONS)
    if kind == "ingress" and (request_id is None or disposition is None):
        return None
    if kind == "attempt" and disposition in (
        "same_key_replay",
        "status_read",
        "non_execution_read",
    ):
        disposition = None
    return Evidence(
        source="insight_event",
        source_id=source_id,
        wallet_id=wallet_id,
        ownership_epoch_id=epoch_id,
        original_operation_anchor_id=anchor_id,
        event_kind=kind,
        request_id=request_id,
        attempt_id=_safe(record["attempt_id"]),
        logical_operation_id=_safe(record["logical_operation_id"]),
        request_disposition=cast(RequestDisposition | None, disposition),
        tool=_safe(record["tool"]),
        reason_code=_safe_reason(record["reason_code"]),
        environment=_safe(record["environment"]),
        server_release=_safe(record["server_release"]),
        deployment=_safe(record["deployment"]),
        client_version=_safe(record["client_version"]),
        occurred_at=_aware(occurred_at),
        ingested_at=_aware(record["ingested_at"]) if record["ingested_at"] else None,
        state_facts=EvidenceStateFacts(
            gateway_outcome=cast(
                GatewayOutcome | None,
                _known(record["gateway_outcome"], _GATEWAY_OUTCOMES),
            ),
            effect_state=cast(
                EffectState | None, _known(record["effect_state"], _EFFECT_STATES)
            ),
        ),
    )


def _event_columns(event_table: Any) -> tuple[Any, ...]:
    return (
        event_table.c.event_id.label("page_id"),
        event_table.c.occurred_at.label("page_time"),
        event_table.c.kind,
        event_table.c.request_id,
        event_table.c.attempt_id,
        event_table.c.logical_operation_id,
        event_table.c.wallet_id,
        event_table.c.ownership_epoch_id,
        event_table.c.original_operation_anchor_id,
        event_table.c.request_disposition,
        event_table.c.tool,
        event_table.c.reason_code,
        event_table.c.gateway_outcome,
        event_table.c.effect_state,
        event_table.c.ingested_at,
        event_table.c.duplicate_conflict_at,
        event_table.c.environment,
        event_table.c.server_release,
        event_table.c.deployment,
        event_table.c.client_version,
    )


def _ref(row: Evidence) -> EvidenceRef:
    return EvidenceRef(
        source=row.source,
        source_id=row.source_id,
        wallet_id=row.wallet_id,
        ownership_epoch_id=row.ownership_epoch_id,
        original_operation_anchor_id=row.original_operation_anchor_id,
    )


def _add_context(
    rows: dict[tuple[str, str], Evidence],
    evidence: Evidence,
    ambiguous: set[tuple[str, str]],
    gaps: set[str],
) -> None:
    key = (evidence.source, evidence.source_id)
    if key in ambiguous:
        return
    previous = rows.get(key)
    if previous is not None and (
        previous.wallet_id != evidence.wallet_id
        or previous.ownership_epoch_id != evidence.ownership_epoch_id
        or previous.original_operation_anchor_id
        != evidence.original_operation_anchor_id
    ):
        rows.pop(key)
        ambiguous.add(key)
        gaps.add("shared_context_anchor_ambiguous")
        return
    rows[key] = evidence


async def _read_legacy_links(
    scope: Scope,
    roots: dict[str, Evidence],
    cutoff: datetime,
    limits: Limits,
    session: AsyncSession,
    rows: dict[tuple[str, str], Evidence],
    gaps: set[str],
    deadline: float,
) -> None:
    """Read exact FK links through a scoped original idempotency anchor."""
    if not roots:
        return
    i = IdempotencyRecordModel
    d = McpDispatchAttemptModel
    l = LedgerEntryModel
    r = ReceiptModel
    p = PermitModel
    pr = PermitRequestModel
    h = HumanApprovalModel
    all_roots = list(roots)
    ambiguous_context: set[tuple[str, str]] = set()
    for offset in range(0, len(all_roots), limits.page_size):
        ids = all_roots[offset : offset + limits.page_size]
        root_scope = and_(
            col(i.record_id).in_(ids),
            _epoch_filter(scope, col(i.wallet_id), col(i.created_at)),
        )
        dispatches: dict[str, Any] = {}
        dispatch_stmt = (
            select(
                col(d.attempt_id).label("page_id"),
                col(d.created_at).label("page_time"),
                col(d.idempotency_record_id),
                col(d.wallet_id),
                col(d.permit_id),
                col(d.approval_id),
                col(d.public_tool_id),
                col(d.ledger_entry_id),
                col(d.credits_charged),
                col(d.state),
                col(d.error_code),
                col(d.dispatched_at),
                col(d.completed_at),
                col(d.debit_refunded_at),
                col(d.budget_released_at),
            )
            .join(
                i,
                and_(
                    col(d.idempotency_record_id) == col(i.record_id),
                    col(d.wallet_id) == col(i.wallet_id),
                ),
            )
            .where(root_scope, col(d.created_at) <= to_naive_utc(cutoff))
        )
        async for page in _keyset(
            session,
            dispatch_stmt,
            col(d.created_at),
            col(d.attempt_id),
            limits.page_size,
            deadline=deadline,
        ):
            for record in page:
                root = roots.get(record["idempotency_record_id"])
                source_id = _safe(record["page_id"])
                if (
                    root is None
                    or source_id is None
                    or record["wallet_id"] != root.wallet_id
                ):
                    gaps.add("dispatch_original_anchor_unverified")
                    continue
                timestamps = [
                    StageTimestamp(
                        "prepared", _aware(record["page_time"]), "dispatch", source_id
                    )
                ]
                for stage, column in (
                    ("dispatch_claimed", "dispatched_at"),
                    ("dispatch_completed", "completed_at"),
                    ("debit_refunded", "debit_refunded_at"),
                    ("budget_released", "budget_released_at"),
                ):
                    if record[column] is not None:
                        timestamps.append(
                            StageTimestamp(
                                stage, _aware(record[column]), "dispatch", source_id
                            )
                        )
                evidence = Evidence(
                    source="dispatch",
                    source_id=source_id,
                    wallet_id=root.wallet_id,
                    ownership_epoch_id=root.ownership_epoch_id,
                    original_operation_anchor_id=root.original_operation_anchor_id,
                    attempt_id=source_id,
                    logical_operation_id=root.source_id,
                    tool=_safe(record["public_tool_id"]),
                    occurred_at=_aware(record["page_time"]),
                    stage_timestamps=tuple(timestamps),
                    reason_code=_safe_reason(record["error_code"]),
                    state_facts=EvidenceStateFacts(
                        dispatch_state=cast(
                            Any, _known(record["state"], _DISPATCH_STATES) or "unknown"
                        ),
                        refund_state="completed"
                        if record["debit_refunded_at"]
                        else "unknown",
                        budget_release_state="completed"
                        if record["budget_released_at"]
                        else "unknown",
                    ),
                    edges=(_ref(root),),
                )
                rows[("dispatch", source_id)] = evidence
                dispatches[source_id] = record

        debits: dict[str, Any] = {}
        debit_stmt: Any = (
            select(
                col(l.entry_id).label("page_id"),
                col(l.timestamp).label("page_time"),
                col(l.wallet_id),
                col(l.action),
                col(l.amount),
                col(l.operation_key),
                col(l.correlation_id),
            )
            .join(
                i,
                and_(
                    col(l.operation_key) == col(i.record_id),
                    col(l.wallet_id) == col(i.wallet_id),
                ),
            )
            .where(
                root_scope,
                col(l.action) == "debit",
                col(l.timestamp) <= to_naive_utc(cutoff),
            )
        )
        async for page in _keyset(
            session,
            debit_stmt,
            col(l.timestamp),
            col(l.entry_id),
            limits.page_size,
            deadline=deadline,
        ):
            for record in page:
                root = roots.get(record["operation_key"])
                source_id = _safe(record["page_id"])
                if root is None or source_id is None:
                    gaps.add("debit_original_anchor_unverified")
                    continue
                linked_dispatch = next(
                    (
                        item
                        for item in dispatches.values()
                        if item["idempotency_record_id"] == root.source_id
                        and item["ledger_entry_id"] == source_id
                    ),
                    None,
                )
                verified = (
                    linked_dispatch is not None
                    and record["amount"] == -linked_dispatch["credits_charged"]
                )
                rows[("ledger", source_id)] = Evidence(
                    source="ledger",
                    source_id=source_id,
                    wallet_id=root.wallet_id,
                    ownership_epoch_id=root.ownership_epoch_id,
                    original_operation_anchor_id=root.original_operation_anchor_id,
                    logical_operation_id=root.source_id,
                    occurred_at=_aware(record["page_time"]),
                    state_facts=EvidenceStateFacts(
                        ledger_action="debit",
                        ledger_link_verified=verified
                        if linked_dispatch is not None
                        else None,
                    ),
                    edges=(_ref(root),),
                )
                debits[source_id] = record
                if linked_dispatch is not None and not verified:
                    gaps.add("debit_amount_mismatch")

        if debits:
            debit_anchor = cast(Any, LedgerEntryModel).__table__.alias("debit_anchor")
            refund_stmt: Any = (
                select(
                    col(l.entry_id).label("page_id"),
                    col(l.timestamp).label("page_time"),
                    col(l.wallet_id),
                    col(l.action),
                    col(l.amount),
                    col(l.correlation_id),
                )
                .join(
                    debit_anchor,
                    and_(
                        col(l.correlation_id) == debit_anchor.c.entry_id,
                        col(l.wallet_id) == debit_anchor.c.wallet_id,
                    ),
                )
                .join(
                    i,
                    and_(
                        debit_anchor.c.operation_key == col(i.record_id),
                        col(l.wallet_id) == col(i.wallet_id),
                    ),
                )
                .where(
                    root_scope,
                    debit_anchor.c.action == "debit",
                    col(l.action) == "refund",
                    col(l.correlation_id).in_(tuple(debits)),
                    col(l.timestamp) <= to_naive_utc(cutoff),
                )
            )
            async for page in _keyset(
                session,
                refund_stmt,
                col(l.timestamp),
                col(l.entry_id),
                limits.page_size,
                deadline=deadline,
            ):
                for record in page:
                    debit = debits.get(record["correlation_id"])
                    if debit is None or debit["wallet_id"] != record["wallet_id"]:
                        gaps.add("refund_owner_mismatch")
                        continue
                    root = roots[debit["operation_key"]]
                    source_id = _safe(record["page_id"])
                    if source_id is None:
                        gaps.add("refund_id_invalid")
                        continue
                    rows[("ledger", source_id)] = Evidence(
                        source="ledger",
                        source_id=source_id,
                        wallet_id=root.wallet_id,
                        ownership_epoch_id=root.ownership_epoch_id,
                        original_operation_anchor_id=root.original_operation_anchor_id,
                        logical_operation_id=root.source_id,
                        occurred_at=_aware(record["page_time"]),
                        state_facts=EvidenceStateFacts(
                            ledger_action="refund",
                            ledger_link_verified=True,
                            refund_amount_matches_debit=record["amount"]
                            == -debit["amount"],
                        ),
                        edges=(_ref(root), _ref(rows[("ledger", debit["page_id"])])),
                    )

        receipts: dict[str, Any] = {}
        receipt_stmt = (
            select(
                col(r.receipt_id).label("page_id"),
                col(r.created_at).label("page_time"),
                col(r.idempotency_record_id),
                col(r.dispatch_attempt_id),
                col(r.permit_id),
                col(r.wallet_id),
                col(r.tool),
                col(r.outcome),
                col(r.reason_code),
                col(r.ledger_entry_id),
                col(r.audit_event_id),
                col(r.approval_id),
            )
            .join(
                i,
                and_(
                    col(r.idempotency_record_id) == col(i.record_id),
                    col(r.wallet_id) == col(i.wallet_id),
                ),
            )
            .where(root_scope, col(r.created_at) <= to_naive_utc(cutoff))
        )
        async for page in _keyset(
            session,
            receipt_stmt,
            col(r.created_at),
            col(r.receipt_id),
            limits.page_size,
            deadline=deadline,
        ):
            for record in page:
                root = roots.get(record["idempotency_record_id"])
                source_id = _safe(record["page_id"])
                if root is None or source_id is None:
                    gaps.add("receipt_original_anchor_unverified")
                    continue
                dispatch = rows.get(("dispatch", record["dispatch_attempt_id"]))
                if dispatch is not None and (
                    dispatch.wallet_id != root.wallet_id
                    or dispatch.ownership_epoch_id != root.ownership_epoch_id
                    or dispatch.original_operation_anchor_id
                    != root.original_operation_anchor_id
                    or dispatch.logical_operation_id != root.source_id
                ):
                    dispatch = None
                if record["dispatch_attempt_id"] and dispatch is None:
                    gaps.add("receipt_dispatch_link_unverified")
                outcome = record["outcome"]
                gateway = (
                    "succeeded"
                    if outcome == "success"
                    else "denied"
                    if outcome == "denied"
                    else "failed"
                    if outcome in ("failed", "failed_refunded", "failed_unrefunded")
                    else "unknown"
                )
                rows[("receipt", source_id)] = Evidence(
                    source="receipt",
                    source_id=source_id,
                    wallet_id=root.wallet_id,
                    ownership_epoch_id=root.ownership_epoch_id,
                    original_operation_anchor_id=root.original_operation_anchor_id,
                    logical_operation_id=root.source_id,
                    tool=_safe(record["tool"]),
                    occurred_at=_aware(record["page_time"]),
                    reason_code=_safe_reason(record["reason_code"]),
                    state_facts=EvidenceStateFacts(gateway_outcome=cast(Any, gateway)),
                    edges=(_ref(root),) + ((_ref(dispatch),) if dispatch else ()),
                )
                receipts[source_id] = record
        if any(
            item["idempotency_record_id"]
            not in {receipt["idempotency_record_id"] for receipt in receipts.values()}
            for item in dispatches.values()
        ):
            gaps.add("dispatch_receipt_missing")

        if dispatches:
            permit_stmt: Any = (
                select(
                    col(p.permit_id).label("page_id"),
                    col(p.issued_at).label("page_time"),
                    col(p.subject_wallet_id),
                    col(p.status),
                    col(p.expires_at),
                    col(p.revoked_at),
                    col(d.idempotency_record_id),
                )
                .join(
                    d,
                    and_(
                        col(p.permit_id) == col(d.permit_id),
                        col(p.subject_wallet_id) == col(d.wallet_id),
                    ),
                )
                .join(
                    i,
                    and_(
                        col(d.idempotency_record_id) == col(i.record_id),
                        col(p.subject_wallet_id) == col(i.wallet_id),
                    ),
                )
                .where(
                    root_scope,
                    col(d.attempt_id).in_(tuple(dispatches)),
                    col(p.issued_at) <= to_naive_utc(cutoff),
                )
            )
            async for page in _keyset(
                session,
                permit_stmt,
                col(p.issued_at),
                col(p.permit_id),
                limits.page_size,
                deadline=deadline,
            ):
                for record in page:
                    root = roots[record["idempotency_record_id"]]
                    source_id = _safe(record["page_id"])
                    if source_id is None:
                        gaps.add("permit_id_invalid")
                        continue
                    _add_context(
                        rows,
                        Evidence(
                            source="permit",
                            source_id=source_id,
                            wallet_id=root.wallet_id,
                            ownership_epoch_id=root.ownership_epoch_id,
                            original_operation_anchor_id=root.original_operation_anchor_id,
                            logical_operation_id=root.source_id,
                            occurred_at=_aware(record["page_time"]),
                            state_facts=EvidenceStateFacts(
                                permit_status=cast(
                                    Any,
                                    record["status"]
                                    if record["status"] in ("active", "revoked")
                                    else "unknown",
                                ),
                                permit_expires_at=_aware(record["expires_at"]),
                                permit_revoked_at=_aware(record["revoked_at"])
                                if record["revoked_at"]
                                else None,
                            ),
                            edges=(_ref(root),),
                        ),
                        ambiguous_context,
                        gaps,
                    )

            approval_stmt: Any = (
                select(
                    col(h.approval_id).label("page_id"),
                    col(h.requested_at).label("page_time"),
                    col(h.wallet_id),
                    col(h.permit_id),
                    col(h.tool),
                    col(h.status),
                    col(h.expires_at),
                    col(h.decided_at),
                    col(d.idempotency_record_id),
                )
                .join(
                    d,
                    and_(
                        col(h.approval_id) == col(d.approval_id),
                        col(h.wallet_id) == col(d.wallet_id),
                        col(h.permit_id) == col(d.permit_id),
                    ),
                )
                .join(
                    i,
                    and_(
                        col(d.idempotency_record_id) == col(i.record_id),
                        col(h.wallet_id) == col(i.wallet_id),
                    ),
                )
                .where(
                    root_scope,
                    col(d.attempt_id).in_(tuple(dispatches)),
                    col(h.requested_at) <= to_naive_utc(cutoff),
                )
            )
            async for page in _keyset(
                session,
                approval_stmt,
                col(h.requested_at),
                col(h.approval_id),
                limits.page_size,
                deadline=deadline,
            ):
                for record in page:
                    root = roots[record["idempotency_record_id"]]
                    source_id = _safe(record["page_id"])
                    if source_id is None:
                        gaps.add("approval_id_invalid")
                        continue
                    status = record["status"]
                    _add_context(
                        rows,
                        Evidence(
                            source="approval",
                            source_id=source_id,
                            wallet_id=root.wallet_id,
                            ownership_epoch_id=root.ownership_epoch_id,
                            original_operation_anchor_id=root.original_operation_anchor_id,
                            logical_operation_id=root.source_id,
                            tool=_safe(record["tool"]),
                            occurred_at=_aware(record["page_time"]),
                            state_facts=EvidenceStateFacts(
                                approval_status=cast(
                                    Any,
                                    status
                                    if status
                                    in (
                                        "pending",
                                        "approved",
                                        "rejected",
                                        "expired",
                                        "consumed",
                                    )
                                    else "unknown",
                                ),
                                approval_expires_at=_aware(record["expires_at"]),
                                approval_decided_at=_aware(record["decided_at"])
                                if record["decided_at"]
                                else None,
                            ),
                            edges=(_ref(root),),
                        ),
                        ambiguous_context,
                        gaps,
                    )

            request_stmt: Any = (
                select(
                    col(pr.request_id).label("page_id"),
                    col(pr.requested_at).label("page_time"),
                    col(pr.subject_wallet_id),
                    col(pr.permit_id),
                    col(pr.status),
                    col(pr.expires_at),
                    col(pr.decided_at),
                    col(d.idempotency_record_id),
                )
                .join(
                    d,
                    or_(
                        col(pr.permit_id) == col(d.permit_id),
                        col(pr.reserved_permit_id) == col(d.permit_id),
                    ),
                )
                .join(
                    i,
                    and_(
                        col(d.idempotency_record_id) == col(i.record_id),
                        col(pr.subject_wallet_id) == col(i.wallet_id),
                        col(d.wallet_id) == col(i.wallet_id),
                    ),
                )
                .where(
                    root_scope,
                    col(d.attempt_id).in_(tuple(dispatches)),
                    col(pr.requested_at) <= to_naive_utc(cutoff),
                )
            )
            async for page in _keyset(
                session,
                request_stmt,
                col(pr.requested_at),
                col(pr.request_id),
                limits.page_size,
                deadline=deadline,
            ):
                for record in page:
                    root = roots[record["idempotency_record_id"]]
                    source_id = _safe(record["page_id"])
                    if source_id is None:
                        gaps.add("permit_request_id_invalid")
                        continue
                    status = record["status"]
                    _add_context(
                        rows,
                        Evidence(
                            source="permit_request",
                            source_id=source_id,
                            wallet_id=root.wallet_id,
                            ownership_epoch_id=root.ownership_epoch_id,
                            original_operation_anchor_id=root.original_operation_anchor_id,
                            logical_operation_id=root.source_id,
                            occurred_at=_aware(record["page_time"]),
                            state_facts=EvidenceStateFacts(
                                permit_request_status=cast(
                                    Any,
                                    status
                                    if status
                                    in (
                                        "pending",
                                        "minting",
                                        "approved",
                                        "rejected",
                                        "expired",
                                        "failed",
                                    )
                                    else "unknown",
                                ),
                            ),
                            edges=(_ref(root),),
                        ),
                        ambiguous_context,
                        gaps,
                    )


async def read_evidence(
    scope: Scope,
    window: Window,
    limits: Limits,
    session: AsyncSession,
) -> EvidenceBatch:
    """Enumerate original operations, then their verified scoped links.

    Historical idempotency creation is a trusted start anchor for governed
    operations. Legacy audit-only/terminal rows have no independently proven
    original epoch and are withheld rather than being re-owned at arrival.
    """
    _bound(scope, session)
    if window.end - window.start > timedelta(days=30):
        raise ValueError("insight_window_exceeds_30_days")
    started = time.monotonic()
    deadline = started + limits.seconds
    cutoff_raw = (await session.execute(select(func.current_timestamp()))).scalar_one()
    cutoff = _aware(cutoff_raw)
    snapshot = Snapshot(
        cutoff=cutoff,
        token=f"snap-{uuid.uuid4().hex}",
        atomic=session.bind is not None and session.bind.dialect.name == "postgresql",
        replica_lag_seconds=None,
    )
    gaps: set[str] = {
        "historical_ingress_not_reconstructable",
        "audit_original_anchor_unverified",
    }
    rows: dict[tuple[str, str], Evidence] = {}
    truncated = False
    source_available = {name: True for name in _SOURCE_NAMES}
    source_available["insight_event"] = await _has_events(session)
    source_available["audit"] = False
    source_available["refund"] = False
    if not source_available["insight_event"]:
        gaps.add("prospective_ingress_unavailable")

    window_ingress: dict[str, Evidence] = {}
    if source_available["insight_event"] and window.time_basis == "ingress":
        e = _EVENTS
        ingress_stmt = select(*_event_columns(e)).where(
            e.c.kind == "ingress",
            _ingress_anchor_filter(scope, e),
            e.c.occurred_at >= to_naive_utc(window.start),
            e.c.occurred_at < to_naive_utc(window.end),
            e.c.ingested_at <= to_naive_utc(cutoff),
            e.c.original_operation_anchor_id.is_not(None),
        )
        async for page in _keyset(
            session,
            ingress_stmt,
            e.c.occurred_at,
            e.c.event_id,
            limits.page_size,
            deadline=deadline,
        ):
            for record in page:
                if record["duplicate_conflict_at"] is not None:
                    gaps.add("ingress_duplicate_conflict")
                    continue
                wallet_id = _safe(record["wallet_id"])
                epoch_id = (
                    _epoch_for(scope, wallet_id, record["page_time"])
                    if wallet_id is not None
                    else None
                )
                evidence = _event_evidence(record, epoch_id) if epoch_id else None
                if evidence is None:
                    gaps.add("ingress_provenance_ambiguous")
                    continue
                window_ingress[evidence.source_id] = evidence
                if len(window_ingress) >= limits.operations:
                    truncated = True
                    break
            if truncated:
                break
        if window.time_basis == "ingress":
            candidate_roots: dict[tuple[str | None, str | None], Evidence] = {}
            ambiguous_anchors: set[tuple[str | None, str | None]] = set()
            for row in window_ingress.values():
                if row.request_disposition != "execution_intent":
                    continue
                key = (row.wallet_id, row.original_operation_anchor_id)
                if key in candidate_roots:
                    ambiguous_anchors.add(key)
                else:
                    candidate_roots[key] = row
            if ambiguous_anchors:
                gaps.add("original_ingress_anchor_conflicting")
            roots = {
                key: row
                for key, row in candidate_roots.items()
                if key not in ambiguous_anchors
            }
            rows.update({(row.source, row.source_id): row for row in roots.values()})
            if roots:
                original = e.alias("original_ingress")
                linked = e.alias("linked_event")
                valid_anchor = exists(
                    select(1)
                    .select_from(original)
                    .where(
                        original.c.kind == "ingress",
                        original.c.wallet_id == linked.c.wallet_id,
                        original.c.original_operation_anchor_id
                        == linked.c.original_operation_anchor_id,
                        _event_epoch_filter(scope, original),
                        original.c.event_id.in_(
                            tuple(row.source_id for row in roots.values())
                        ),
                    )
                )
                linked_stmt = select(*_event_columns(linked)).where(
                    linked.c.kind.in_(("attempt", "terminal")),
                    linked.c.wallet_id.in_(scope.wallet_ids),
                    linked.c.original_operation_anchor_id.in_(
                        tuple(anchor for _, anchor in roots if anchor is not None)
                    ),
                    linked.c.ingested_at <= to_naive_utc(cutoff),
                    valid_anchor,
                )
                async for page in _keyset(
                    session,
                    linked_stmt,
                    linked.c.occurred_at,
                    linked.c.event_id,
                    limits.page_size,
                    deadline=deadline,
                ):
                    for record in page:
                        if record["duplicate_conflict_at"] is not None:
                            gaps.add("linked_event_duplicate_conflict")
                            continue
                        root = roots.get(
                            (
                                record["wallet_id"],
                                record["original_operation_anchor_id"],
                            )
                        )
                        evidence = (
                            _event_evidence(record, root.ownership_epoch_id)
                            if root
                            else None
                        )
                        if root is None or evidence is None:
                            gaps.add("linked_event_provenance_ambiguous")
                            continue
                        rows[(evidence.source, evidence.source_id)] = replace(
                            evidence, edges=(_ref(root),)
                        )

    if window.time_basis == "first_observed_evidence":
        idem = IdempotencyRecordModel
        record_id = col(idem.record_id)
        created_at = col(idem.created_at)
        wallet_id_col = col(idem.wallet_id)
        root_stmt: Any = select(
            record_id.label("page_id"),
            created_at.label("page_time"),
            wallet_id_col,
        ).where(
            _epoch_filter(scope, wallet_id_col, created_at),
            or_(
                col(idem.endpoint).in_(_GOVERNED_ENDPOINTS),
                col(idem.endpoint).like("/mcp/tools/%/invoke"),
            ),
            created_at >= to_naive_utc(window.start),
            created_at < to_naive_utc(window.end),
            created_at <= to_naive_utc(cutoff),
        )
        async for page in _keyset(
            session,
            root_stmt,
            created_at,
            record_id,
            limits.page_size,
            deadline=deadline,
        ):
            for root in page:
                source_id = _safe(root["page_id"])
                wallet_id = _safe(root["wallet_id"])
                epoch_id = (
                    _epoch_for(scope, wallet_id, root["page_time"])
                    if wallet_id is not None
                    else None
                )
                if source_id is None or wallet_id is None or epoch_id is None:
                    gaps.add("original_ownership_ambiguous")
                    continue
                rows[("idempotency", source_id)] = Evidence(
                    source="idempotency",
                    source_id=source_id,
                    wallet_id=wallet_id,
                    ownership_epoch_id=epoch_id,
                    original_operation_anchor_id=source_id,
                    logical_operation_id=source_id,
                    occurred_at=_aware(root["page_time"]),
                    state_facts=EvidenceStateFacts(idempotency_outcome="unknown"),
                )
                if len(rows) >= limits.operations:
                    truncated = True
                    break
            if truncated:
                break
        await _read_legacy_links(
            scope,
            {
                source_id: row
                for (source, source_id), row in rows.items()
                if source == "idempotency"
            },
            cutoff,
            limits,
            session,
            rows,
            gaps,
            deadline,
        )
    # Prospective event enumeration is added when the disabled-by-default
    # event table lands. Its absence must never be treated as zero ingress.
    if window.time_basis == "ingress" and not source_available["insight_event"]:
        gaps.add("ingress_enumeration_unavailable")
    if truncated:
        gaps.add("operation_limit_reached")
    if not snapshot.atomic:
        gaps.add("non_atomic_snapshot")
    # The legacy stores cannot independently prove original ownership for
    # orphaned audit/terminal evidence, and permit context may be shared by
    # several operations. A fully traversed SQL table is not full capture.
    incomplete_sources = {
        "insight_event",
        "idempotency",
        "dispatch",
        "ledger",
        "audit",
        "receipt",
        "permit",
        "permit_request",
        "approval",
        "refund",
    }
    if source_available["insight_event"]:
        gaps.add("prospective_capture_completeness_unverified")
    gaps.add("historical_retention_unverified")
    gaps.add("legacy_unanchored_evidence_withheld")
    gaps.add("audit_anchor_unverified")
    gaps.add("refund_work_item_unreadable")
    coverage = Coverage(
        sources=tuple(
            SourceCoverage(
                source=name,
                availability="available" if source_available[name] else "unavailable",
                enumeration_complete=(
                    not truncated
                    and source_available[name]
                    and name not in incomplete_sources
                ),
                truncated=truncated,
                gaps=(
                    ("audit_anchor_unverified",)
                    if name == "audit"
                    else ("refund_work_item_unreadable",)
                    if name == "refund"
                    else ("source_unavailable",)
                    if not source_available[name]
                    else ("capture_completeness_unverified",)
                    if name == "insight_event"
                    else ("surviving_roots_only", "retention_unverified")
                    if name in ("idempotency", "dispatch", "ledger")
                    else ("unanchored_rows_withheld",)
                    if name in incomplete_sources
                    else ()
                ),
            )
            for name in _SOURCE_NAMES
        ),
        enumeration_complete=False,
        truncated=truncated,
        consistency_flags=() if snapshot.atomic else ("non_atomic_snapshot",),
        gaps=tuple(sorted(gaps)),
    )
    return EvidenceBatch(
        rows=tuple(rows.values()),
        snapshot=snapshot,
        coverage=coverage,
        window_ingress=tuple(window_ingress.values()),
    )


async def read_unknown_wallet_count(
    scope: Scope, window: Window, session: AsyncSession
) -> UnknownWalletCount:
    """Return only a fixed full-day 7/30-day aggregate, when permissioned."""
    _bound(scope, session)
    if not scope.allow_unknown_wallet_counts:
        return UnknownWalletCount(status="not_authorized")
    duration = window.end - window.start
    if duration not in (timedelta(days=7), timedelta(days=30)):
        return UnknownWalletCount(status="unavailable")
    bucket_end = window.end.replace(hour=0, minute=0, second=0, microsecond=0)
    bucket_start = bucket_end - duration
    if not await _has_events(session):
        return UnknownWalletCount(
            status="unavailable", bucket_start=bucket_start, bucket_end=bucket_end
        )
    # Table presence cannot certify lossless delivery for the full 7/30 days.
    # No durable capture watermark exists yet; even an empty table is not zero.
    return UnknownWalletCount(
        status="partial", bucket_start=bucket_start, bucket_end=bucket_end
    )
