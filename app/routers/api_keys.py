"""
API Key Management Router

Handles API key creation, rotation, and revocation for wallet security.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..core.auth import AuthContext, get_auth_context
from ..services.api_key_service import (
    get_api_key_service,
    InvalidRotationRequestError,
    KeyNotFoundError,
    WalletNotFoundError,
)
from ..schemas.billing import (
    CreateAPIKeyRequest,
    APIKeyResponse,
    APIKeyWithSecret,
    APIKeyListResponse,
    RotateAPIKeyRequest,
    RotationResponse,
    KeyRotationLogEntry,
    EmergencyKeyRevocationRequest,
    RotationType,
)

router = APIRouter(
    prefix="/v1/api-keys",
    tags=["API Key Management"],
    responses={
        401: {"description": "Missing API key"},
        403: {"description": "Insufficient permissions"},
    },
)


def _not_found(error: str, message: str) -> dict:
    """Standardized 404 error payload."""
    return {"error": error, "message": message}


def _invalid_request(error: str, message: str) -> dict:
    """Standardized 422 error payload."""
    return {"error": error, "message": message}


async def _refuse_bounded_minter(auth: AuthContext) -> None:
    """Refuse to mint a fresh key for a caller whose own key is bounded.

    POST /v1/api-keys and rotate without key_id issue a key carrying only
    the bounds the request names, and both are reachable with the wallet's
    own key (or a JWT derived from it). A key with a use budget or an expiry
    could otherwise mint an unlimited, never-expiring sibling and outlive its
    own limits. Rotating the bounded key itself (key_id set) stays allowed:
    that path carries its remaining bounds over. Bootstrap admins and
    unbounded wallet keys are unaffected.
    """
    if auth.is_bootstrap_admin:
        return
    if not await get_api_key_service().is_key_bounded(auth.key_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error": "bounded_key_cannot_mint",
            "message": (
                "This API key has a use budget or an expiry, so it cannot "
                "mint new keys. Rotate it with key_id and revoke_old to carry "
                "its remaining bounds over, or ask a bootstrap admin for a key "
                "with fresh bounds."
            ),
        },
    )


@router.post(
    "",
    response_model=APIKeyWithSecret,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new API key",
    description=(
        "Create a new API key for a wallet. The key is only shown once "
        "- store it securely."
    ),
)
async def create_api_key(
    request: CreateAPIKeyRequest,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Create a new API key for a wallet.

    Returns the full API key which is only shown once.
    Store it securely - it cannot be retrieved later.
    """
    auth.require_wallet_access(request.wallet_id)
    await _refuse_bounded_minter(auth)
    service = get_api_key_service()

    try:
        result = await service.create_key(
            wallet_id=request.wallet_id,
            key_name=request.key_name,
            expires_in_days=request.expires_in_days,
            max_uses=request.max_uses,
        )
        return APIKeyWithSecret(
            key_id=result["key_id"],
            wallet_id=result["wallet_id"],
            api_key=result["api_key"],
            key_prefix=result["key_prefix"],
            status=result["status"],
            key_name=result["key_name"],
            created_at=result["created_at"],
            expires_at=result["expires_at"],
            max_uses=result["max_uses"],
        )
    except WalletNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=_not_found("wallet_not_found", str(e)),
        )


@router.get(
    "/{wallet_id}",
    response_model=APIKeyListResponse,
    summary="List API keys for a wallet",
    description="Get all API keys for a wallet. Keys are masked for security.",
)
async def list_api_keys(
    wallet_id: str,
    auth: AuthContext = Depends(get_auth_context),
):
    """List all API keys for a wallet."""
    auth.require_wallet_access(wallet_id)
    service = get_api_key_service()

    try:
        result = await service.get_keys(wallet_id)
        return APIKeyListResponse(
            wallet_id=result["wallet_id"],
            keys=[APIKeyResponse(**k) for k in result["keys"]],
            total_active=result["total_active"],
            total_revoked=result["total_revoked"],
        )
    except WalletNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=_not_found("wallet_not_found", str(e)),
        )


@router.post(
    "/rotate",
    response_model=RotationResponse,
    summary="Rotate an API key",
    description=(
        "Rotate an API key by creating a new one and optionally revoking the old one. "
        "Returns the new key which is only shown once."
    ),
)
async def rotate_api_key(
    request: RotateAPIKeyRequest,
    http_request: Request,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Rotate an API key.

    Creates a new key and optionally revokes the old one.
    """
    auth.require_wallet_access(request.wallet_id)
    if request.key_id is None:
        # Without key_id this is a plain create with no bounds to inherit.
        await _refuse_bounded_minter(auth)
    service = get_api_key_service()

    client_ip = http_request.client.host if http_request.client else None

    try:
        result = await service.rotate_key(
            wallet_id=request.wallet_id,
            key_id=request.key_id,
            revoke_old=request.revoke_old,
            reason=request.reason,
            triggered_by="user",
            ip_address=client_ip,
        )

        new_key = None
        if result["new_key"]:
            new_key = APIKeyWithSecret(
                key_id=result["new_key"]["key_id"],
                wallet_id=result["new_key"]["wallet_id"],
                api_key=result["new_key"]["api_key"],
                key_prefix=result["new_key"]["key_prefix"],
                status=result["new_key"]["status"],
                key_name=result["new_key"]["key_name"],
                created_at=result["new_key"]["created_at"],
                expires_at=result["new_key"]["expires_at"],
                max_uses=result["new_key"]["max_uses"],
            )

        return RotationResponse(
            rotation_id=result["rotation_id"],
            wallet_id=result["wallet_id"],
            old_key_id=result["old_key_id"],
            new_key=new_key,
            rotation_type=RotationType(result["rotation_type"]),
            revoked_keys=result["revoked_keys"],
            created_at=result["created_at"],
        )
    except WalletNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=_not_found("wallet_not_found", str(e)),
        )
    except KeyNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=_not_found("key_not_found", str(e)),
        )
    except InvalidRotationRequestError as e:
        raise HTTPException(
            status_code=422,
            detail=_invalid_request("invalid_rotation_request", str(e)),
        )


@router.delete(
    "/{wallet_id}/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
    description="Immediately revoke an API key. This action cannot be undone.",
)
async def revoke_api_key(
    wallet_id: str,
    key_id: str,
    reason: str = "user_request",
    auth: AuthContext = Depends(get_auth_context),
):
    """Revoke an API key immediately."""
    auth.require_wallet_access(wallet_id)
    service = get_api_key_service()

    try:
        await service.revoke_key(wallet_id, key_id, reason)
    except WalletNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=_not_found("wallet_not_found", str(e)),
        )
    except KeyNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=_not_found("key_not_found", str(e)),
        )


@router.post(
    "/emergency-revoke",
    summary="Emergency key revocation",
    description=(
        "Immediately revoke ALL API keys for a wallet. Use for security incidents."
    ),
)
async def emergency_revoke(
    request: EmergencyKeyRevocationRequest,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    Emergency revocation - revoke all keys for a wallet.

    Use this when a wallet may be compromised.
    Optionally creates a new emergency key.
    """
    auth.require_wallet_access(request.wallet_id)
    service = get_api_key_service()

    try:
        result = await service.emergency_revocation(
            wallet_id=request.wallet_id,
            reason=request.reason,
            create_new_key=request.create_new_key,
        )

        new_key = None
        if result["new_key"]:
            new_key = APIKeyWithSecret(
                key_id=result["new_key"]["key_id"],
                wallet_id=result["new_key"]["wallet_id"],
                api_key=result["new_key"]["api_key"],
                key_prefix=result["new_key"]["key_prefix"],
                status=result["new_key"]["status"],
                key_name=result["new_key"]["key_name"],
                created_at=result["new_key"]["created_at"],
                expires_at=result["new_key"]["expires_at"],
                max_uses=result["new_key"]["max_uses"],
            )

        return {
            "wallet_id": result["wallet_id"],
            "revoked_keys": result["revoked_keys"],
            "new_key": new_key,
            "created_at": result["created_at"].isoformat(),
        }
    except WalletNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=_not_found("wallet_not_found", str(e)),
        )


@router.get(
    "/{wallet_id}/logs",
    response_model=list[KeyRotationLogEntry],
    summary="Get rotation audit logs",
    description="Get audit logs for API key rotations on a wallet.",
)
async def get_rotation_logs(
    wallet_id: str,
    limit: int = 50,
    auth: AuthContext = Depends(get_auth_context),
):
    """Get rotation audit logs for a wallet."""
    auth.require_wallet_access(wallet_id)
    service = get_api_key_service()

    try:
        logs = await service.get_rotation_logs(wallet_id, limit)
        return [KeyRotationLogEntry(**log) for log in logs]
    except WalletNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=_not_found("wallet_not_found", str(e)),
        )
