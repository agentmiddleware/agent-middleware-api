"""JWT authentication endpoints.

Modern token-based auth alongside legacy API keys.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import update
from sqlalchemy.sql.elements import ColumnElement

from app.core.jwt import (
    JWT_AUTHORITY_SCOPES,
    JWTError,
    get_jwt_service,
    has_jwt_authority_scope_profile,
)
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


def _exp_to_datetime(ts: int) -> datetime:
    """Convert JWT exp (int) to timezone-aware datetime."""
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _normalize_authority_scopes(requested: list[str] | None) -> list[str]:
    """Return the one JWT profile the current authorization layer supports."""
    if requested is None:
        return list(JWT_AUTHORITY_SCOPES)
    if not has_jwt_authority_scope_profile(requested):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "unsupported_jwt_scope_profile",
                "message": (
                    "JWT scope attenuation is not supported. Request exactly "
                    f"{' '.join(JWT_AUTHORITY_SCOPES)} or omit scopes."
                ),
            },
        )
    return list(JWT_AUTHORITY_SCOPES)


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

    scopes = _normalize_authority_scopes(request.scopes)

    access_token = jwt_svc.create_access_token(
        wallet_id=db_key.wallet_id,
        key_id=db_key.key_id,
        scopes=scopes,
    )
    refresh_token = jwt_svc.create_refresh_token(
        wallet_id=db_key.wallet_id,
        key_id=db_key.key_id,
        scopes=scopes,
    )

    # Store refresh token JTI for revocation
    refresh_payload = jwt_svc.verify_refresh_token(refresh_token)
    factory = get_session_factory()
    async with factory() as session:
        model = RefreshTokenModel(
            jti=refresh_payload.jti,
            wallet_id=db_key.wallet_id,
            # Bind the chain to the key that minted it, so revoking that key
            # invalidates what it produced even when sibling keys stay active.
            key_id=db_key.key_id,
            expires_at=_exp_to_datetime(refresh_payload.exp),
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

    # Refresh JWTs minted before the fixed-profile contract do not carry enough
    # information to preserve their original authority. Never infer it from a
    # wallet or from the database row: require the caller to re-present a key.
    if payload.key_id is None or not has_jwt_authority_scope_profile(payload.scopes):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "invalid_refresh_token",
                "message": (
                    "This refresh token predates the supported authority profile "
                    "and cannot be renewed; authenticate with an active API key."
                ),
            },
        )

    origin_key_id = payload.key_id
    scopes = list(JWT_AUTHORITY_SCOPES)

    from app.services.api_key_service import get_api_key_service

    key_svc = get_api_key_service()
    still_live = await key_svc.is_key_live(origin_key_id)
    if not still_live:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "no_active_api_key",
                "message": (
                    "The API key this token was issued from is no longer active; "
                    "it cannot be renewed."
                ),
            },
        )

    # Issue new tokens
    new_access = jwt_svc.create_access_token(
        wallet_id=payload.sub,
        key_id=origin_key_id,
        scopes=scopes,
    )
    new_refresh = jwt_svc.create_refresh_token(
        wallet_id=payload.sub,
        key_id=origin_key_id,
        scopes=scopes,
    )

    # Consume the parent and persist its sole child in one transaction. The
    # revoked=False predicate is the compare-and-swap primitive: concurrent
    # refreshes may all verify the JWT, but only one can update one row.
    new_refresh_payload = jwt_svc.verify_refresh_token(new_refresh)
    factory = get_session_factory()
    failed_reason: str | None = None
    async with factory() as session:
        async with session.begin():
            consumed = await session.execute(
                update(RefreshTokenModel)
                .where(
                    cast(
                        ColumnElement[bool],
                        RefreshTokenModel.jti == payload.jti,
                    ),
                    cast(
                        ColumnElement[bool],
                        RefreshTokenModel.wallet_id == payload.sub,
                    ),
                    cast(
                        ColumnElement[bool],
                        RefreshTokenModel.key_id == origin_key_id,
                    ),
                    cast(Any, RefreshTokenModel.revoked).is_(False),
                )
                .values(revoked=True)
            )
            if (cast(Any, consumed).rowcount or 0) != 1:
                # Preserve the old fail-closed behavior for a partially restored
                # database whose token row lost its key binding. This update is
                # also conditional and commits without creating a child.
                unbound = await session.execute(
                    update(RefreshTokenModel)
                    .where(
                        cast(
                            ColumnElement[bool],
                            RefreshTokenModel.jti == payload.jti,
                        ),
                        cast(
                            ColumnElement[bool],
                            RefreshTokenModel.wallet_id == payload.sub,
                        ),
                        cast(Any, RefreshTokenModel.key_id).is_(None),
                        cast(Any, RefreshTokenModel.revoked).is_(False),
                    )
                    .values(revoked=True)
                )
                if (cast(Any, unbound).rowcount or 0) == 1:
                    failed_reason = "unbound_refresh_token"
                else:
                    failed_reason = "revoked_refresh_token"
            else:
                session.add(
                    RefreshTokenModel(
                        jti=new_refresh_payload.jti,
                        wallet_id=payload.sub,
                        key_id=origin_key_id,
                        expires_at=_exp_to_datetime(new_refresh_payload.exp),
                    )
                )

    if failed_reason is not None:
        message = (
            "This refresh token is no longer bound to its originating API key."
            if failed_reason == "unbound_refresh_token"
            else "Token has been revoked."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": failed_reason, "message": message},
        )

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
