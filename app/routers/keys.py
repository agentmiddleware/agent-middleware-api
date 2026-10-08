from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import AuthContext, get_auth_context
from app.schemas.trust import RotateSigningKeyRequest, SigningKeyResponse
from app.services.signing_keys import SigningKeyError
from app.trust import get_signing_key_service

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


def _signing_key_failure(error: str) -> HTTPException:
    """Map a SigningKeyError code to the matching HTTP response."""
    if error == "signing_key_not_found":
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": error,
                "message": "No signing key with that id.",
            },
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "error": error,
            "message": "The signing key operation was refused.",
        },
    )


@router.post("/rotate", response_model=SigningKeyResponse)
async def rotate_signing_key(
    request: RotateSigningKeyRequest,
    auth: AuthContext = Depends(get_auth_context),
) -> SigningKeyResponse:
    """Rotate the active receipt-signing key id (operator only).

    Publishes ``new_key_id`` as the active key and retires the previous one;
    retired keys stay published so old receipts remain verifiable.
    """

    auth.require_bootstrap_admin()
    try:
        key = await get_signing_key_service().rotate_active_key_metadata(
            request.new_key_id.strip()
        )
    except SigningKeyError as exc:
        raise _signing_key_failure(str(exc)) from exc
    return _key_response(key)


@router.post("/{key_id}/retire", response_model=SigningKeyResponse)
async def retire_signing_key(
    key_id: str,
    auth: AuthContext = Depends(get_auth_context),
) -> SigningKeyResponse:
    """Retire a signing key id (operator only).

    Retired keys stay published so old receipts remain verifiable. The
    currently active id cannot be retired: signing would re-activate it on
    the next receipt, so rotate to a new id first.
    """

    auth.require_bootstrap_admin()
    service = get_signing_key_service()
    try:
        active = await service.get_active_key()
    except SigningKeyError as exc:
        raise _signing_key_failure(str(exc)) from exc
    if active.key_id == key_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "cannot_retire_active_key",
                "message": (
                    "This id is the active signing key; rotate to a new id "
                    "first, then retire it."
                ),
            },
        )
    try:
        key = await service.retire_key_metadata(key_id)
    except SigningKeyError as exc:
        raise _signing_key_failure(str(exc)) from exc
    return _key_response(key)
