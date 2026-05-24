from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import AuthContext, get_auth_context
from app.trust import TrustReadinessReport, build_trust_readiness_report

router = APIRouter(prefix="/v1/trust", tags=["Trust Readiness"])


@router.get(
    "/readiness",
    response_model=TrustReadinessReport,
    summary="Trust-plane readiness gap map",
    description=(
        "Operator-only report that separates verified trust-plane capabilities "
        "from partially verified, demo-only, or not-yet-claimable gaps. This is "
        "not a certification of production readiness."
    ),
)
async def get_trust_readiness(
    auth: AuthContext = Depends(get_auth_context),
) -> TrustReadinessReport:
    auth.require_bootstrap_admin()
    return build_trust_readiness_report()
