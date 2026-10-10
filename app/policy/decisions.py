from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
import uuid

from app.core.auth import AuthContext


@dataclass(frozen=True)
class PolicyDecision:
    decision_id: str
    allowed: bool
    reason: str
    wallet_id: str
    tool_name: str
    auth_source: str
    key_id: str | None
    estimated_cost: float | None
    request_id: str | None

    def model_dump(self, **_: Any) -> dict[str, Any]:
        return asdict(self)


def evaluate_wallet_access_for_tool(
    *,
    auth: AuthContext,
    wallet_id: str,
    tool_name: str,
    estimated_cost: float | None,
    request_id: str | None,
) -> PolicyDecision:
    """Check wallet ownership for a tool call, nothing else.

    This is a tenant-isolation check only: it passes when the caller is the
    bootstrap admin or owns ``wallet_id``. It does not check permits, wallet
    policy bundles, budgets, scopes, or human approvals. Every caller that
    authorizes a real tool call must enforce those separately after this
    check (see docs/POLICY_ENFORCEMENT.md layers B and C). A decision with
    ``allowed=True`` here is never sufficient on its own to run a tool.
    """
    if auth.is_bootstrap_admin or auth.wallet_id == wallet_id:
        return PolicyDecision(
            decision_id=f"pol-{uuid.uuid4().hex[:16]}",
            allowed=True,
            reason="allowed",
            wallet_id=wallet_id,
            tool_name=tool_name,
            auth_source=auth.source,
            key_id=auth.key_id,
            estimated_cost=estimated_cost,
            request_id=request_id,
        )

    return PolicyDecision(
        decision_id=f"pol-{uuid.uuid4().hex[:16]}",
        allowed=False,
        reason="wallet_access_denied",
        wallet_id=wallet_id,
        tool_name=tool_name,
        auth_source=auth.source,
        key_id=auth.key_id,
        estimated_cost=estimated_cost,
        request_id=request_id,
    )


# Kept for backward compatibility. New code should call
# evaluate_wallet_access_for_tool, which says what is actually checked.
evaluate_tool_invocation = evaluate_wallet_access_for_tool


def evaluate_governed_action(
    *,
    auth: AuthContext | None,
    wallet_id: str | None,
    action_type: str,
    target: str,
    estimated_cost: float | None = None,
    request_id: str | None = None,
    allowed: bool | None = None,
    reason: str | None = None,
) -> PolicyDecision:
    """Create the shared policy-shaped decision used by governed actions.

    When the caller passes ``allowed``/``reason`` explicitly, this records
    that caller-side outcome; it does not re-derive it. When they are left
    unset, the default allow derives only from wallet identity, exactly like
    evaluate_wallet_access_for_tool: it never checks permits, policy
    bundles, budgets, or approvals.
    """
    auth_source = (
        "bootstrap"
        if auth and auth.is_bootstrap_admin
        else (auth.source if auth else "anonymous")
    )
    key_id = auth.key_id if auth else None

    if allowed is None:
        allowed = bool(
            auth
            and wallet_id
            and (auth.is_bootstrap_admin or auth.wallet_id == wallet_id)
        )
    if reason is None:
        reason = "allowed" if allowed else "wallet_access_denied"

    return PolicyDecision(
        decision_id=f"pol-{uuid.uuid4().hex[:16]}",
        allowed=allowed,
        reason=reason,
        wallet_id=wallet_id or "",
        tool_name=target or action_type,
        auth_source=auth_source,
        key_id=key_id,
        estimated_cost=estimated_cost,
        request_id=request_id,
    )
