"""
Capability permit endpoints: issue, introspect, and publish the signing key.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..core.auth import AuthContext, get_auth_context
from ..services.permits import PermitError, get_permit_service

router = APIRouter(prefix="/v1/permits", tags=["permits"])


class PermitIssueRequest(BaseModel):
    wallet_id: str = Field(..., description="Wallet the permit acts for")
    scope: list[str] = Field(
        ..., description="Allowed tool names / service ids ('*' = any)"
    )
    max_spend: float | None = Field(
        None, description="Optional credit ceiling for the permit"
    )
    ttl_seconds: int | None = Field(
        None, ge=1, description="Lifetime in seconds (defaults to server setting)"
    )
    agent_id: str | None = Field(None, description="Agent the permit is issued to")
    single_use: bool = Field(
        False, description="If true, the permit can be redeemed only once"
    )


class PermitIntrospectRequest(BaseModel):
    permit: str = Field(..., description="The permit token to verify")


@router.post("/issue", summary="Issue a signed scoped capability permit")
async def issue_permit(
    request: PermitIssueRequest,
    auth: AuthContext = Depends(get_auth_context),
) -> dict[str, Any]:
    auth.require_wallet_access(request.wallet_id)
    service = get_permit_service()
    issued = service.issue(
        wallet_id=request.wallet_id,
        scope=request.scope,
        max_spend=request.max_spend,
        ttl_seconds=request.ttl_seconds,
        agent_id=request.agent_id,
        single_use=request.single_use,
    )
    return {
        "permit": issued["permit"],
        "claims": issued["claims"],
        "algorithm": service.algorithm,
    }


@router.get("/public-key", summary="Permit signing public key")
async def permit_public_key() -> dict[str, Any]:
    service = get_permit_service()
    return {
        "algorithm": service.algorithm,
        "public_key": service.public_key_b64(),
        "encoding": "base64",
        "verifiable_offline": service.algorithm == "ed25519",
    }


@router.post("/introspect", summary="Verify a permit and return its claims")
async def introspect_permit(
    request: PermitIntrospectRequest,
    auth: AuthContext = Depends(get_auth_context),
) -> dict[str, Any]:
    service = get_permit_service()
    try:
        claims = service.decode(request.permit)
    except PermitError as exc:
        return {"valid": False, "error": str(exc)}
    return {"valid": True, "claims": claims}
