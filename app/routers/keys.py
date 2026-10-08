from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import AuthContext, get_auth_context
from app.schemas.trust import SigningKeyResponse
from app.trust import SigningKeyError, get_signing_key_service

router = APIRouter(prefix="/v1/signing-keys", tags=["Trust Signing Keys"])


def _key_response(key) -> SigningKeyResponse:
    return SigningKeyResponse(
        key_id=key.key_id,
        alg=key.alg,
        public_key_b64=key.public_key_b64,
        status=key.status,
        created_at=key.created_at,
        activated_at=key.activated_at,
        retired_at=key.retired_at,
    )


@router.get("/active", response_model=SigningKeyResponse)
async def get_active_signing_key(
    auth: AuthContext = Depends(get_auth_context),
) -> SigningKeyResponse:
    """Return public metadata for the active transaction-evidence signing key."""

    key = await get_signing_key_service().get_active_key()
    return _key_response(key)


@router.get("/{key_id}", response_model=SigningKeyResponse)
async def get_signing_key(
    key_id: str,
    auth: AuthContext = Depends(get_auth_context),
) -> SigningKeyResponse:
    """Return public metadata for an active or retired signing key."""

    key = await get_signing_key_service().get_public_key(key_id)
    if not key:
        raise HTTPException(status_code=404, detail="signing_key_not_found")
    return _key_response(key)


@router.post("/{key_id}/retire", response_model=SigningKeyResponse)
async def retire_signing_key(
    key_id: str,
    auth: AuthContext = Depends(get_auth_context),
) -> SigningKeyResponse:
    """Retire a superseded signing key after a redeploy rotation.

    Bootstrap admin only. Rotation itself is still a redeploy with a new
    ``TRUST_SIGNING_PRIVATE_KEY_B64`` paired with a new
    ``TRUST_SIGNING_KEY_ID`` (see ``docs/key-management.md``); this route
    completes that flow by marking the old metadata row ``retired``.
    Retired keys stay queryable so receipts signed under them keep
    verifying. Retiring the key the server is currently signing with is
    refused: ``ensure_active_key`` would reactivate it on the next
    signature, so the redeploy must come first.
    """

    auth.require_bootstrap_admin()
    service = get_signing_key_service()
    active = await service.get_active_key()
    if key_id == active.key_id:
        raise HTTPException(
            status_code=409,
            detail="signing_key_is_active",
        )
    try:
        key = await service.retire_key_metadata(key_id)
    except SigningKeyError as exc:
        if str(exc) == "signing_key_not_found":
            raise HTTPException(
                status_code=404, detail="signing_key_not_found"
            ) from exc
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _key_response(key)
