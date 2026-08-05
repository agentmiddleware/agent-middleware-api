"""JWT authentication endpoints.

Modern token-based auth alongside legacy API keys.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import AuthContext, get_auth_context
from app.core.jwt import JWTError, get_jwt_service
from app.core.time import utc_now
from app.db.database import get_session_factory
from app.db.models import RefreshTokenModel
from app.schemas.auth import (
    TokenExchangeRequest,
    TokenExchangeResponse,
    TokenRefreshRequest,
    TokenRefreshResponse,
    TokenRevokeRequest,
)

router = APIRouter(prefix="/v1/auth", tags=["Authentication"])


@router.post("/token", response_model=TokenExchangeResponse)
async def exchange_api_key_for_tokens(
    request: TokenExchangeRequest,
) -> TokenExchangeResponse:
    """Exchange a wallet API key for short-lived JWT tokens.

    Returns an access token (15 min) and refresh token (7 days).
    The refresh token can be used at /v1/auth/refresh to obtain
    a new access token without re-presenting the API key.
    """
    from app.services.api_key_service import get_api_key_service

    # Validate the API key
    key_svc = get_api_key_service()
    db_key = await key_svc.validate_key(request.api_key)
    if not db_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_api_key", "message": "API key is not valid."},
        )

    jwt_svc = get_jwt_service()

    # Default scopes: all billing and tool invoke
    scopes = request.scopes or ["billing:charge", "tool:invoke"]

    access_token = jwt_svc.create_access_token(
        wallet_id=db_key.wallet_id,
        key_id=db_key.key_id,
        scopes=scopes,
    )
    refresh_token = jwt_svc.create_refresh_token(wallet_id=db_key.wallet_id)

    # Store refresh token JTI for revocation
    refresh_payload = jwt_svc.verify_refresh_token(refresh_token)
    factory = get_session_factory()
    async with factory() as session:
        model = RefreshTokenModel(
            jti=refresh_payload.jti,
            wallet_id=db_key.wallet_id,
            expires_at=refresh_payload.exp,
        )
        session.add(model)
        await session.commit()

    return TokenExchangeResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer",
        expires_in=900,  # 15 minutes
        scope=" ".join(scopes),
    )


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh_access_token(
    request: TokenRefreshRequest,
) -> TokenRefreshResponse:
    """Exchange a refresh token for a new access token.

    Refresh token rotation: a new refresh token is issued on each use,
    and the old one is marked as revoked.
    """
    jwt_svc = get_jwt_service()

    try:
        payload = jwt_svc.verify_refresh_token(request.refresh_token)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_refresh_token", "message": str(e)},
        ) from e

    # Check if revoked in DB
    factory = get_session_factory()
    async with factory() as session:
        record = await session.get(RefreshTokenModel, payload.jti)
        if not record or record.revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "revoked_refresh_token", "message": "Token has been revoked."},
            )

        # Mark old refresh token as revoked
        record.revoked = True
        await session.commit()

    # Issue new tokens
    new_access = jwt_svc.create_access_token(
        wallet_id=payload.sub,
        key_id=None,  # Refresh tokens don't carry key_id
        scopes=["billing:charge", "tool:invoke"],
    )
    new_refresh = jwt_svc.create_refresh_token(wallet_id=payload.sub)

    # Store new refresh token
    new_refresh_payload = jwt_svc.verify_refresh_token(new_refresh)
    async with factory() as session:
        model = RefreshTokenModel(
            jti=new_refresh_payload.jti,
            wallet_id=payload.sub,
            expires_at=new_refresh_payload.exp,
        )
        session.add(model)
        await session.commit()

    return TokenRefreshResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        token_type="Bearer",
        expires_in=900,
    )


@router.post("/revoke")
async def revoke_refresh_token(
    request: TokenRevokeRequest,
) -> dict[str, str]:
    """Revoke a refresh token by JTI.

    Prevents the token from being used at /v1/auth/refresh.
    """
    jwt_svc = get_jwt_service()

    try:
        payload = jwt_svc.verify_refresh_token(request.refresh_token)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_refresh_token", "message": str(e)},
        ) from e

    factory = get_session_factory()
    async with factory() as session:
        record = await session.get(RefreshTokenModel, payload.jti)
        if record:
            record.revoked = True
            await session.commit()

    return {"status": "revoked"}
