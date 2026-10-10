"""Deterministic classifications from scoped, bounded evidence facts."""

from __future__ import annotations

from dataclasses import replace
from typing import TypeVar

from app.services.operation_insights.contracts import (
    EffectState,
    Evidence,
    FailureClass,
    GatewayOutcome,
    NextAction,
    Operation,
    RecoveryState,
)

_VALIDATION_CODES = frozenset(
    {
        "idempotency_key_not_a_string",
        "idempotency_key_blank",
        "idempotency_key_too_long",
        "idempotency_key_control_characters",
        "idempotency_key_not_utf8",
        "idempotency_key_conflict",
        "invalid_idempotency_key",
    }
)
_DENIAL_CODES = _VALIDATION_CODES | frozenset(
    {
        "action_permit_denied",
        "action_permit_required",
        "duplicate_request_new_key",
        "human_approval_pending",
        "idempotency_key_reused",
        "insufficient_funds",
        "permit_budget_exceeded",
        "permit_denied",
        "permit_max_calls_exceeded",
        "permit_not_found",
        "permit_recipient_domain_mismatch",
        "permit_required",
        "policy_denied",
    }
)
_FAULT_CODES = frozenset(
    {
        "audit_chain_contended_after_effects",
        "delivery_uncertain",
        "internal_error",
        "mcp_upstream_delivery_uncertain",
        "receipt_write_contended_after_effects",
        "refund_failed",
        "tool_execution_failed",
        "upstream_pre_dispatch_failed",
        "upstream_response_invalid",
        "upstream_returned_error",
    }
)

State = TypeVar("State", GatewayOutcome, EffectState, RecoveryState)


def _state(values: list[State], unknown: State) -> State:
    explicit = {value for value in values if value != "unknown"}
    if "conflicting" in explicit or len(explicit) > 1:
        return "conflicting"  # type: ignore[return-value]
    return next(iter(explicit), unknown)


def _failure_stage(row: Evidence) -> str:
    if row.reason_code == "refund_failed" or row.state_facts.refund_state == "failed":
        return "refund"
    if row.reason_code in _DENIAL_CODES:
        return "validation" if row.reason_code in _VALIDATION_CODES else "authorization"
    if row.state_facts.policy_decision == "deny":
        return "policy"
    return "dispatch" if row.source == "dispatch" else row.source


def classify(operation: Operation, evidence: tuple[Evidence, ...]) -> Operation:
    """A receipt, dispatch claim, or refund never proves a remote effect."""
    if any(
        row.wallet_id != operation.wallet_id
        or row.ownership_epoch_id != operation.ownership_epoch_id
        or row.original_operation_anchor_id != operation.original_operation_anchor_id
        for row in evidence
    ):
        raise ValueError("classification evidence crosses operation provenance")
    gaps = set(operation.evidence_gaps)
    conflicts = set(operation.conflicts)
    gateway_values: list[GatewayOutcome] = []
    effect_values: list[EffectState] = []
    refund_values: list[RecoveryState] = []
    budget_values: list[RecoveryState] = []
    refund_claimed = False
    refund_verified = False
    refund_mismatch = False
    for row in evidence:
        facts = row.state_facts
        if facts.gateway_outcome is not None:
            gateway_values.append(facts.gateway_outcome)
        if row.source == "dispatch":
            if facts.dispatch_state == "succeeded":
                gateway_values.append("succeeded")
            elif facts.dispatch_state in ("returned_error", "response_rejected"):
                gateway_values.append("failed")
        if facts.policy_decision == "deny":
            gateway_values.append("denied")
        if facts.idempotency_outcome == "payload_mismatch":
            gateway_values.append("denied")
        if facts.effect_state is not None:
            effect_values.append(facts.effect_state)
        if facts.refund_state is not None:
            if facts.refund_state == "completed":
                refund_claimed = True
            else:
                refund_values.append(facts.refund_state)
        if row.source == "ledger" and facts.ledger_action == "refund":
            if facts.ledger_link_verified and facts.refund_amount_matches_debit:
                refund_verified = True
            elif (
                facts.ledger_link_verified is False
                or facts.refund_amount_matches_debit is False
            ):
                refund_mismatch = True
        if facts.budget_release_state is not None:
            budget_values.append(facts.budget_release_state)
    if refund_verified:
        refund_values.append("completed")
    if refund_claimed and not refund_verified:
        gaps.add("refund_unverified")
    if refund_mismatch:
        conflicts.add("refund_evidence_conflict")
        refund_values.append("conflicting")
    gateway = _state(gateway_values, "unknown")
    effect = _state(effect_values, "unknown")
    refund = _state(refund_values, "unknown")
    budget = _state(budget_values, "unknown")
    for name, value in (
        ("gateway", gateway),
        ("effect", effect),
        ("refund", refund),
        ("budget_release", budget),
    ):
        if value == "conflicting":
            conflicts.add(f"{name}_state_conflict")
    has_dispatch = any(row.source == "dispatch" for row in evidence)
    has_receipt = any(row.source == "receipt" for row in evidence)
    if has_dispatch and not has_receipt:
        gaps.add("receipt_missing")
    if effect == "unknown" and (
        has_receipt
        or any(
            row.state_facts.dispatch_state
            in ("dispatch_claimed", "dispatched", "succeeded", "delivery_uncertain")
            for row in evidence
        )
    ):
        gaps.add("effect_proof_missing")
    reason_rows = [row for row in evidence if row.reason_code is not None]
    reason = reason_rows[0].reason_code if reason_rows else None
    if len({row.reason_code for row in reason_rows}) > 1:
        conflicts.add("reason_code_conflict")
    denial_rows = [
        row
        for row in evidence
        if row.reason_code in _DENIAL_CODES
        or row.state_facts.policy_decision == "deny"
        or row.state_facts.gateway_outcome == "denied"
        or row.state_facts.idempotency_outcome == "payload_mismatch"
        or row.state_facts.approval_status in ("rejected", "expired")
        or row.state_facts.permit_request_status in ("rejected", "expired")
    ]
    fault_rows = [
        row
        for row in evidence
        if row.reason_code in _FAULT_CODES
        or row.state_facts.gateway_outcome == "failed"
        or row.state_facts.refund_state == "failed"
        or row.state_facts.dispatch_state
        in ("returned_error", "delivery_uncertain", "response_rejected")
    ]
    if fault_rows and denial_rows:
        failure_class: FailureClass = "conflicting"
    elif fault_rows:
        failure_class = "unexpected_fault"
    elif denial_rows:
        failure_class = "expected_denial"
    elif gateway == "succeeded":
        failure_class = "none"
    else:
        failure_class = "unknown"
    classified_rows = fault_rows or denial_rows
    failure_stage = _failure_stage(classified_rows[0]) if classified_rows else None
    unresolved = (
        gateway in ("unknown", "conflicting")
        or effect in ("unknown", "conflicting")
        or refund in ("unknown", "conflicting", "failed", "pending")
        or budget in ("unknown", "conflicting", "failed", "pending")
    )
    observed_times = [
        at for row in evidence if (at := row.occurred_at or row.ingested_at) is not None
    ]
    observed_times.extend(point.at for point in operation.stage_timestamps)
    if (
        conflicts
        or (effect == "confirmed" and gateway in ("unknown", "conflicting"))
        or (
            gateway != "succeeded"
            and any(
                row.state_facts.dispatch_state
                in ("dispatch_claimed", "dispatched", "delivery_uncertain")
                for row in evidence
            )
        )
    ):
        action: NextAction = "manual_review"
    elif refund in ("failed", "pending") or any(
        row.state_facts.dispatch_state == "prepared"
        or row.state_facts.ledger_action == "debit"
        for row in evidence
    ):
        action = "reconcile"
    else:
        action = "inspect"
    return replace(
        operation,
        gateway_outcome=gateway,
        effect_state=effect,
        refund_state=refund,
        budget_release_state=budget,
        reason_code=reason,
        failure_class=failure_class,
        failure_stage=failure_stage,
        observed_fault=True
        if fault_rows
        else (False if failure_class == "none" else None),
        observed_denial=True
        if denial_rows
        else (False if failure_class == "none" else None),
        unresolved_since=(
            min(observed_times) if observed_times else operation.first_seen_at
        )
        if unresolved
        else None,
        evidence_gaps=tuple(sorted(gaps)),
        conflicts=tuple(sorted(conflicts)),
        next_action=action,
    )
