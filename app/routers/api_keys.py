"""
API Key Management Router

Handles API key creation, rotation, and revocation for wallet security.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..core.auth import verify_api_key
from ..services.api_key_service import (
    get_api_key_service,
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
    api_key: str = Depends(verify_api_key),
):
    """
    Create a new API key for a wallet.

    Returns the full API key which is only shown once.
    Store it securely - it cannot be retrieved later.
    """
    service = get_api_key_service()

    try:
        result = await service.create_key(
            wallet_id=request.wallet_id,
            key_name=request.key_name,
            expires_in_days=request.expires_in_days,
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
        )
    except WalletNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/{wallet_id}",
    response_model=APIKeyListResponse,
    summary="List API keys for a wallet",
    description="Get all API keys for a wallet. Keys are masked for security.",
)
async def list_api_keys(
    wallet_id: str,
    api_key: str = Depends(verify_api_key),
):
    """List all API keys for a wallet."""
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
        raise HTTPException(status_code=404, detail=str(e))


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
    api_key: str = Depends(verify_api_key),
):
    """
    Rotate an API key.

    Creates a new key and optionally revokes the old one.
    """
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
        raise HTTPException(status_code=404, detail=str(e))
    except KeyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


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
    api_key: str = Depends(verify_api_key),
):
    """Revoke an API key immediately."""
    service = get_api_key_service()

    try:
        await service.revoke_key(wallet_id, key_id, reason)
    except WalletNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except KeyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/emergency-revoke",
    summary="Emergency key revocation",
    description=(
        "Immediately revoke ALL API keys for a wallet. Use for security incidents."
    ),
)
async def emergency_revoke(
    request: EmergencyKeyRevocationRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Emergency revocation - revoke all keys for a wallet.

    Use this when a wallet may be compromised.
    Optionally creates a new emergency key.
    """
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
            )

        return {
            "wallet_id": result["wallet_id"],
            "revoked_keys": result["revoked_keys"],
            "new_key": new_key,
            "created_at": result["created_at"].isoformat(),
        }
    except WalletNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/{wallet_id}/logs",
    response_model=list[KeyRotationLogEntry],
    summary="Get rotation audit logs",
    description="Get audit logs for API key rotations on a wallet.",
)
async def get_rotation_logs(
    wallet_id: str,
    limit: int = 50,
    api_key: str = Depends(verify_api_key),
):
    """Get rotation audit logs for a wallet."""
    service = get_api_key_service()

    try:
        logs = await service.get_rotation_logs(wallet_id, limit)
        return [KeyRotationLogEntry(**log) for log in logs]
    except WalletNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
