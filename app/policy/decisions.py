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

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_tool_invocation(
    *,
    auth: AuthContext,
    wallet_id: str,
    tool_name: str,
    estimated_cost: float | None,
    request_id: str | None,
) -> PolicyDecision:
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
