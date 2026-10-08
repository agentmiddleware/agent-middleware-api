from __future__ import annotations

from typing import Any

from app.core.auth import AuthContext
from app.policy.decisions import PolicyDecision, evaluate_governed_action
from app.services.audit_log import record_audit_event


async def record_governed_action(
    *,
    event: str,
    auth: AuthContext | None,
    wallet_id: str | None,
    target: str,
    endpoint: str | None,
    request_id: str | None = None,
    estimated_cost: float | None = None,
    committed_cost: float | None = None,
    allowed: bool = False,
    reason: str | None = None,
    ok: bool = True,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> PolicyDecision:
    """Record an audit event for a governed action, without authorizing it.

    ``allowed`` must be the outcome the caller already decided through real
    enforcement (wallet ownership, permit validation,
    ``evaluate_wallet_policy``). This function only writes that verdict into
    the audit trail; it performs no policy check of its own. The default is
    fail-closed (``allowed=False``), so a caller that forgets to pass its
    verdict records a denial, never an allow.
    """
    if reason is None:
        reason = "allowed" if allowed else "denied"
    decision = evaluate_governed_action(
        auth=auth,
        wallet_id=wallet_id,
        action_type=event,
        target=target,
        estimated_cost=estimated_cost,
        request_id=request_id,
        allowed=allowed,
        reason=reason,
    )
    audit_metadata = {
        "action_type": event,
        "target": target,
        "policy_reason": decision.reason,
        "estimated_cost": estimated_cost,
        "committed_cost": committed_cost,
    }
    if metadata:
        audit_metadata.update(metadata)

    await record_audit_event(
        event=event,
        wallet_id=wallet_id,
        tool=target,
        endpoint=endpoint,
        auth_source=decision.auth_source,
        key_id=decision.key_id,
        policy_decision_id=decision.decision_id,
        request_id=request_id,
        ok=ok,
        error=error,
        metadata=audit_metadata,
    )
    return decision
