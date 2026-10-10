"""Payload-free, opt-in observations of gateway operations."""

from __future__ import annotations

import asyncio
import re
import os
from collections.abc import Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass as standard_dataclass
from dataclasses import fields
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, cast

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult

from app.core.config import get_settings
from app.core.build_metadata import get_build_commit_sha, get_build_provenance
from app.core.time import to_naive_utc, utc_now
from app.db.database import get_session_factory
from app.db.models import InsightEventModel

from .contracts import (
    CLASSIFICATION_VERSION,
    EffectState,
    GatewayOutcome,
    ReasonCode,
    RequestDisposition,
    SafeId,
    UtcDateTime,
)


_delivery_metrics = {"generated": 0, "delivered": 0, "failures": 0}
_pending_events: set[asyncio.Task[None]] = set()
_MAX_PENDING_EVENTS = 256
_SAFE_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_REASON_CODES = frozenset(
    {
        "action_permit_denied",
        "action_permit_required",
        "action_quote_unsupported",
        "action_tool_binding_required",
        "delivery_uncertain",
        "governed_tool_error",
        "human_approval_pending",
        "idempotency_key_required",
        "idempotency_key_required_for_human_approval",
        "idempotency_key_reused",
        "insufficient_funds",
        "internal_error",
        "method_not_found",
        "operation_contended",
        "permit_aggregate_value_cap_exceeded",
        "permit_budget_exceeded",
        "permit_budget_exceeds_wallet_balance",
        "permit_constraint_unsupported_for_upstream",
        "permit_denied",
        "permit_expired",
        "permit_forbidden_field",
        "permit_key_mismatch",
        "permit_max_calls_exceeded",
        "permit_not_found",
        "permit_recipient_domain_mismatch",
        "permit_required",
        "permit_revoked",
        "permit_scope_missing",
        "permit_signature_invalid",
        "permit_tool_not_allowed",
        "permit_wallet_mismatch",
        "policy_denied",
        "request_validation_denied",
        "response_rejected",
        "terminal_record_contended",
        "tool_execution_failed",
        "tool_not_executable",
        "tool_not_found",
        "tool_permission_denied",
        "upstream_pre_dispatch_failed",
        "upstream_returned_error",
        "wallet_expired",
        "wallet_frozen",
        "wallet_scoped_key_required",
    }
)


@standard_dataclass
class RequestEventContext:
    request_id: str
    ingress_event_id: str
    request_disposition: RequestDisposition
    wallet_id: str | None = None
    tool: str | None = None
    logical_operation_id: str | None = None
    reason_code: str | None = None
    gateway_outcome: GatewayOutcome | None = None
    client_version: str | None = None
    environment: str | None = None
    server_release: str | None = None
    deployment: str | None = None


_current_request: ContextVar[RequestEventContext | None] = ContextVar(
    "insight_event_request", default=None
)


def activate_request(context: RequestEventContext) -> Token[RequestEventContext | None]:
    return _current_request.set(context)


def deactivate_request(token: Token[RequestEventContext | None]) -> None:
    _current_request.reset(token)


def mark_current_request(
    *,
    disposition: RequestDisposition | None = None,
    wallet_id: str | None = None,
    tool: str | None = None,
    logical_operation_id: str | None = None,
    reason_code: str | None = None,
    gateway_outcome: GatewayOutcome | None = None,
) -> None:
    """Add only verified handler facts to the current server-issued identity."""
    context = _current_request.get()
    if context is None:
        return
    if disposition in {
        "execution_intent",
        "same_key_replay",
        "status_read",
        "non_execution_read",
        "unknown",
    }:
        context.request_disposition = disposition
    for name, value in (
        ("wallet_id", wallet_id),
        ("tool", tool),
        ("logical_operation_id", logical_operation_id),
    ):
        if value is not None and _SAFE_ID.fullmatch(value):
            setattr(context, name, value)
    normalized_reason = allowlisted_reason_code(reason_code)
    if normalized_reason is not None and context.reason_code is None:
        context.reason_code = normalized_reason
    if gateway_outcome in {"succeeded", "failed", "denied", "unknown", "conflicting"}:
        context.gateway_outcome = gateway_outcome


def original_anchor(context: RequestEventContext) -> str | None:
    """Choose a trusted durable operation ID or a verified denied ingress."""
    if context.logical_operation_id is not None:
        return context.logical_operation_id
    if (
        context.wallet_id is not None
        and context.request_disposition == "execution_intent"
    ):
        return context.ingress_event_id
    return None


@dataclass(
    config=ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )
)
class InsightEvent:
    """Only typed, bounded facts may cross into event persistence."""

    event_id: SafeId
    kind: Literal["ingress", "terminal", "attempt"]
    occurred_at: UtcDateTime
    request_id: SafeId | None = None
    attempt_id: SafeId | None = None
    logical_operation_id: SafeId | None = None
    wallet_id: SafeId | None = None
    ownership_epoch_id: SafeId | None = None
    original_operation_anchor_id: SafeId | None = None
    request_disposition: RequestDisposition | None = None
    tool: SafeId | None = None
    reason_code: ReasonCode | None = None
    gateway_outcome: GatewayOutcome | None = None
    effect_state: EffectState | None = None
    http_status_code: Annotated[int, Field(ge=100, le=599)] | None = None
    classification_version: Literal[1] = CLASSIFICATION_VERSION
    environment: SafeId | None = None
    server_release: SafeId | None = None
    deployment: SafeId | None = None
    client_version: SafeId | None = None

    def __post_init__(self) -> None:
        if self.kind == "ingress" and self.request_id is None:
            raise ValueError("ingress event requires server request identity")
        if self.kind == "attempt" and self.attempt_id is None:
            raise ValueError("attempt event requires server attempt identity")
        if self.kind != "terminal" and self.http_status_code is not None:
            raise ValueError("HTTP status is only a terminal response observation")
        if (
            self.reason_code is not None
            and allowlisted_reason_code(self.reason_code) is None
        ):
            raise ValueError("event_reason_not_allowlisted")


def normalize_client_version(value: str | None, allowed: frozenset[str]) -> str | None:
    """Keep only a deployment-approved, exact client version token."""
    if value is None or len(value) > 64 or not _SAFE_ID.fullmatch(value):
        return None
    return value if value in allowed else None


def allowlisted_reason_code(value: object) -> str | None:
    """Reject free text even when it has the shape of a safe identifier."""
    return value if isinstance(value, str) and value in _REASON_CODES else None


def bounded_governed_reason(
    *, receipt: Mapping[str, object] | None, exception_reason: str, fallback: str
) -> str:
    """A receipt's fixed reason takes precedence over exception text."""
    source = receipt.get("reason_code") if receipt is not None else exception_reason
    return allowlisted_reason_code(source) or fallback


async def record_event(event: InsightEvent) -> None:
    """Insert once; retain a bounded coverage flag if an ID is reused differently."""
    settings = get_settings()
    allowed = frozenset(
        version.strip()
        for version in settings.OPERATION_INSIGHTS_ALLOWED_CLIENT_VERSIONS.split(",")
        if version.strip()
    )
    values = {field.name: getattr(event, field.name) for field in fields(event)}
    values["occurred_at"] = to_naive_utc(event.occurred_at)
    values["client_version"] = normalize_client_version(event.client_version, allowed)
    values["ingested_at"] = utc_now()
    factory = get_session_factory()
    async with factory() as session:
        dialect = session.get_bind().dialect.name
        if dialect == "sqlite":
            statement: Any = sqlite_insert(InsightEventModel)
        elif dialect == "postgresql":
            statement = postgresql_insert(InsightEventModel)
        else:
            raise RuntimeError("insight_event_backend_unsupported")
        result = cast(
            CursorResult[Any],
            await session.execute(
                statement.values(**values).on_conflict_do_nothing(
                    index_elements=["event_id"]
                )
            ),
        )
        if result.rowcount == 0:
            existing = await session.get(InsightEventModel, event.event_id)
            if existing is None:
                raise RuntimeError("insight_event_duplicate_unavailable")
            if any(
                _duplicate_conflicts(existing, name, value)
                for name, value in values.items()
                if name != "ingested_at"
            ):
                existing.duplicate_conflict_at = utc_now()
                session.add(existing)
        await session.commit()


def _duplicate_conflicts(existing: InsightEventModel, name: str, value: Any) -> bool:
    stored = getattr(existing, name)
    if stored == value:
        return False
    if existing.kind == "ingress":
        if name == "request_disposition" and value == "unknown":
            return False
        if (
            name
            in {
                "wallet_id",
                "tool",
                "logical_operation_id",
                "original_operation_anchor_id",
            }
            and value is None
        ):
            return False
    return True


def get_delivery_metrics() -> dict[str, int]:
    """Return worker-local delivery counts, without event content or errors."""
    return {**_delivery_metrics, "pending": len(_pending_events)}


async def observe_event_safely(
    event: InsightEvent, *, generated_already: bool = False
) -> None:
    """An event sink is never part of a business transaction or retry decision."""
    if not generated_already:
        _delivery_metrics["generated"] += 1
    try:
        await record_event(event)
    except Exception:
        _delivery_metrics["failures"] += 1
    else:
        _delivery_metrics["delivered"] += 1


async def observe_event_bounded(event: InsightEvent) -> None:
    """Give ingress/terminal a short delivery chance without holding the app."""
    task = _queue_event(event)
    if task is not None:
        await _wait_briefly(task)


async def enrich_ingress_bounded(context: RequestEventContext) -> None:
    """Bound post-handler enrichment independently from response delivery."""
    if len(_pending_events) >= _MAX_PENDING_EVENTS:
        _delivery_metrics["failures"] += 1
        return
    try:
        task = asyncio.create_task(enrich_ingress_safely(context))
        _pending_events.add(task)
        task.add_done_callback(_finish_pending_event)
    except Exception:
        _delivery_metrics["failures"] += 1
        return
    await _wait_briefly(task)


async def _wait_briefly(task: asyncio.Task[None]) -> None:
    done, _ = await asyncio.wait({task}, timeout=0.1)
    if not done:
        task.cancel()


async def enrich_ingress_safely(context: RequestEventContext) -> None:
    """Narrow an unknown ingress classification after trusted handler checks."""
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = await session.get(
                InsightEventModel, context.ingress_event_id, with_for_update=True
            )
            if row is None:
                return
            for name, incoming in (
                ("request_disposition", context.request_disposition),
                ("wallet_id", context.wallet_id),
                ("tool", context.tool),
                ("logical_operation_id", context.logical_operation_id),
                ("original_operation_anchor_id", original_anchor(context)),
            ):
                if incoming is None:
                    continue
                existing = getattr(row, name)
                if existing == incoming:
                    continue
                if existing is None or (
                    name == "request_disposition" and existing == "unknown"
                ):
                    setattr(row, name, incoming)
                else:
                    row.duplicate_conflict_at = utc_now()
            session.add(row)
            await session.commit()
    except Exception:
        _delivery_metrics["failures"] += 1


async def observe_attempt(
    *,
    attempt_id: str,
    wallet_id: str,
    tool: str,
    logical_operation_id: str | None,
) -> None:
    """Record a real, server-established execution boundary once."""
    try:
        event = _attempt_event(
            attempt_id=attempt_id,
            wallet_id=wallet_id,
            tool=tool,
            logical_operation_id=logical_operation_id,
        )
    except Exception:
        _delivery_metrics["failures"] += 1
        return
    if event is not None:
        await observe_event_safely(event)


def schedule_attempt(
    *,
    attempt_id: str,
    wallet_id: str,
    tool: str,
    logical_operation_id: str | None,
) -> None:
    """Capture trusted facts now, then deliver without delaying execution."""
    try:
        event = _attempt_event(
            attempt_id=attempt_id,
            wallet_id=wallet_id,
            tool=tool,
            logical_operation_id=logical_operation_id,
        )
        if event is None:
            return
        _queue_event(event)
    except Exception:
        _delivery_metrics["failures"] += 1


def _queue_event(event: InsightEvent) -> asyncio.Task[None] | None:
    _delivery_metrics["generated"] += 1
    if len(_pending_events) >= _MAX_PENDING_EVENTS:
        _delivery_metrics["failures"] += 1
        return None
    try:
        task = asyncio.create_task(observe_event_safely(event, generated_already=True))
        _pending_events.add(task)
        task.add_done_callback(_finish_pending_event)
        return task
    except Exception:
        _delivery_metrics["failures"] += 1
        return None


def _finish_pending_event(task: asyncio.Task[None]) -> None:
    _pending_events.discard(task)
    if task.cancelled():
        _delivery_metrics["failures"] += 1
    elif task.exception() is not None:
        _delivery_metrics["failures"] += 1


async def wait_for_pending_events() -> None:
    """Drain currently scheduled events during orderly local shutdown/tests."""
    if _pending_events:
        await asyncio.gather(*tuple(_pending_events), return_exceptions=True)


def _attempt_event(
    *,
    attempt_id: str,
    wallet_id: str,
    tool: str,
    logical_operation_id: str | None,
) -> InsightEvent | None:
    settings = get_settings()
    if not settings.OPERATION_INSIGHTS_EVENTS_ENABLED:
        return None
    context = _current_request.get()
    if context is not None:
        mark_current_request(
            disposition="execution_intent",
            wallet_id=wallet_id,
            tool=tool,
            logical_operation_id=logical_operation_id,
        )
    return InsightEvent(
        event_id=f"evt-{attempt_id}-attempt",
        kind="attempt",
        occurred_at=datetime.now(timezone.utc),
        request_id=context.request_id if context is not None else None,
        attempt_id=attempt_id,
        logical_operation_id=logical_operation_id,
        original_operation_anchor_id=(
            original_anchor(context) if context is not None else logical_operation_id
        ),
        wallet_id=wallet_id,
        tool=tool,
        request_disposition="execution_intent",
        environment=(
            context.environment
            if context is not None
            else _safe_token(settings.ENVIRONMENT)
        ),
        server_release=(
            context.server_release if context is not None else safe_server_release()
        ),
        deployment=(
            context.deployment
            if context is not None
            else _safe_token(os.environ.get("RAILWAY_DEPLOYMENT_ID"))
        ),
        client_version=context.client_version if context is not None else None,
    )


def _safe_token(value: str | None) -> str | None:
    return value if value is not None and _SAFE_ID.fullmatch(value) else None


def safe_server_release() -> str | None:
    """Withhold attribution when build and deploy commit evidence disagree."""
    try:
        if get_build_provenance() == "mismatch":
            return None
        return _safe_token(get_build_commit_sha())
    except Exception:
        return None
