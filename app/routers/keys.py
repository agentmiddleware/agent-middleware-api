from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import AuthContext, get_auth_context
from app.schemas.trust import (
    SigningKeyListResponse,
    SigningKeyResponse,
    SigningKeyRetireRequest,
    SigningKeyRotateRequest,
)
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


def _signing_key_http_error(exc: SigningKeyError) -> HTTPException:
    """Map service-layer key errors to stable operator-facing statuses."""

    # SigningKeyError messages are fixed code strings with no caller input
    # interpolated, so they are safe to return as the response detail.
    code = str(exc)
    if code == "signing_key_not_found":
        return HTTPException(status_code=404, detail=code)
    if code in (
        "signing_key_id_public_key_mismatch",
        "signing_key_disabled",
        "signing_key_not_active",
        "signing_key_is_active",
    ):
        return HTTPException(status_code=409, detail=code)
    return HTTPException(status_code=400, detail=code)


@router.get("/", response_model=SigningKeyListResponse)
async def list_signing_keys(
    auth: AuthContext = Depends(get_auth_context),
) -> SigningKeyListResponse:
    """List every published signing key, newest activation first.

    During a rollover window more than one key reads ``active`` here: the
    configured key signs new artifacts while the previous key keeps
    verifying history under its own ``kid`` until it is retired.
    """

    keys = await get_signing_key_service().list_public_keys()
    return SigningKeyListResponse(
        keys=[_key_response(key) for key in keys], total=len(keys)
    )


@router.post("/rotate", response_model=SigningKeyResponse)
async def rotate_signing_key(
    body: SigningKeyRotateRequest,
    auth: AuthContext = Depends(get_auth_context),
) -> SigningKeyResponse:
    """Move signing to a new key id and retire the previous one.

    Bootstrap admins only. The new id is bound to this gateway's current
    signing material: reusing an id bound to different material, or a
    disabled id, is refused with 409 and the active key is untouched.
    After rotating, restart or redeploy every gateway replica with the new
    ``TRUST_SIGNING_KEY_ID`` so all signers converge; until then replicas
    still on the old id keep signing artifacts that verify under its kid.
    """

    auth.require_bootstrap_admin()
    try:
        key = await get_signing_key_service().rotate_active_key_metadata(
            body.new_key_id
        )
    except SigningKeyError as exc:
        raise _signing_key_http_error(exc) from exc
    return _key_response(key)


@router.post("/retire", response_model=SigningKeyResponse)
async def retire_signing_key(
    body: SigningKeyRetireRequest,
    auth: AuthContext = Depends(get_auth_context),
) -> SigningKeyResponse:
    """Retire a superseded signing key without breaking history.

    Bootstrap admins only. Retired keys stay published so receipts signed
    under their kid keep verifying. The key currently signing cannot be
    retired (rotate first); retiring it would leave the next signature to
    silently reactivate it. Retiring an already-retired key is a no-op
    success.
    """

    auth.require_bootstrap_admin()
    service = get_signing_key_service()
    try:
        active = await service.get_active_key()
    except SigningKeyError as exc:
        raise _signing_key_http_error(exc) from exc
    if body.key_id == active.key_id:
        raise HTTPException(status_code=409, detail="signing_key_is_active")
    try:
        key = await service.retire_key_metadata(body.key_id)
    except SigningKeyError as exc:
        raise _signing_key_http_error(exc) from exc
    return _key_response(key)
