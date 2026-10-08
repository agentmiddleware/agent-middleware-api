from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import AuthContext, get_auth_context
from app.schemas.policies import (
    PolicyBundleCreate,
    PolicyBundleListResponse,
    PolicyBundlePatch,
    PolicyBundleResponse,
)
from app.services.policies import (
    create_policy_bundle,
    deactivate_policy_bundle,
    get_policy_bundle,
    list_policy_bundles,
    patch_policy_bundle,
)

router = APIRouter(prefix="/v1/policies", tags=["Policy Bundles"])


def _require_bundle_access(auth: AuthContext, wallet_id: str) -> None:
    """Bootstrap admins manage any wallet; otherwise the caller must own it.

    Wallet-scoped API keys carry their wallet in ``auth.wallet_id``, so a key
    owner can manage their own wallet's guardrails without operator help.
    """
    auth.require_wallet_access(wallet_id)


@router.post(
    "", response_model=PolicyBundleResponse, status_code=status.HTTP_201_CREATED
)
async def create_policy(
    request: PolicyBundleCreate,
    auth: AuthContext = Depends(get_auth_context),
) -> PolicyBundleResponse:
    _require_bundle_access(auth, request.wallet_id)
    return await create_policy_bundle(request)


@router.get("", response_model=PolicyBundleListResponse)
async def list_policies(
    wallet_id: str | None = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> PolicyBundleListResponse:
    if auth.is_bootstrap_admin:
        policies = await list_policy_bundles(wallet_id=wallet_id)
        return PolicyBundleListResponse(policies=policies, total=len(policies))
    # A wallet key owner lists only their own bundles. An unfiltered list is
    # scoped to the caller's wallet; a filter for another wallet is denied.
    scoped_wallet_id = wallet_id or auth.wallet_id
    _require_bundle_access(auth, scoped_wallet_id or "")
    policies = await list_policy_bundles(wallet_id=scoped_wallet_id)
    return PolicyBundleListResponse(policies=policies, total=len(policies))


@router.get("/{policy_id}", response_model=PolicyBundleResponse)
async def get_policy(
    policy_id: str,
    auth: AuthContext = Depends(get_auth_context),
) -> PolicyBundleResponse:
    policy = await get_policy_bundle(policy_id)
    if not policy:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "policy_not_found",
                "message": f"Policy {policy_id} not found",
            },
        )
    _require_bundle_access(auth, policy.wallet_id)
    return policy


@router.patch("/{policy_id}", response_model=PolicyBundleResponse)
async def patch_policy(
    policy_id: str,
    request: PolicyBundlePatch,
    auth: AuthContext = Depends(get_auth_context),
) -> PolicyBundleResponse:
    existing = await get_policy_bundle(policy_id)
    if not existing:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "policy_not_found",
                "message": f"Policy {policy_id} not found",
            },
        )
    _require_bundle_access(auth, existing.wallet_id)
    policy = await patch_policy_bundle(policy_id, request)
    if not policy:  # pragma: no cover - deleted between the two reads
        raise HTTPException(
            status_code=404,
            detail={
                "error": "policy_not_found",
                "message": f"Policy {policy_id} not found",
            },
        )
    return policy


@router.delete("/{policy_id}", response_model=PolicyBundleResponse)
async def delete_policy(
    policy_id: str,
    auth: AuthContext = Depends(get_auth_context),
) -> PolicyBundleResponse:
    """Deactivate a policy bundle.

    Deactivation is a soft delete: the bundle stays in history with
    ``is_active=false`` and stops being evaluated. Use PATCH to re-activate.
    """
    existing = await get_policy_bundle(policy_id)
    if not existing:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "policy_not_found",
                "message": f"Policy {policy_id} not found",
            },
        )
    _require_bundle_access(auth, existing.wallet_id)
    policy = await deactivate_policy_bundle(policy_id)
    if not policy:  # pragma: no cover - deleted between the two reads
        raise HTTPException(
            status_code=404,
            detail={
                "error": "policy_not_found",
                "message": f"Policy {policy_id} not found",
            },
        )
    return policy
