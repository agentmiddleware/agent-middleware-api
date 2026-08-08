"""
API Key + JWT Bearer authentication for agent consumers.

Agents pass credentials via:
- X-API-Key header (legacy, long-lived keys)
- Authorization: Bearer <jwt> header (modern, short-lived tokens)
"""

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from .config import get_settings
from .trust_mode import is_production_like_environment

settings = get_settings()

api_key_header = APIKeyHeader(
    name=settings.API_KEY_HEADER,
    auto_error=False,
    description="API key for agent authentication. Pass in the X-API-Key header.",
)


@dataclass(frozen=True)
class AuthContext:
    """Authenticated caller details used for tenant-scoped authorization."""

    source: str
    raw_key: str
    key_id: str | None = None
    wallet_id: str | None = None
    is_bootstrap_admin: bool = False
    scopes: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.scopes is None:
            object.__setattr__(self, "scopes", [])

    def require_wallet_access(self, wallet_id: str | None) -> None:
        """Allow bootstrap admins or the exact wallet owning a DB-backed key.

        ``wallet_id`` may be ``None`` for a resource with no owning wallet (e.g.
        a sandbox environment created by a bootstrap admin). A non-admin caller
        always has a concrete ``self.wallet_id``, so an ownerless resource is
        correctly denied to everyone but bootstrap admins.
        """
        if self.is_bootstrap_admin:
            return
        if self.wallet_id is not None and self.wallet_id == wallet_id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "wallet_access_denied",
                "message": "API key is not authorized for this wallet.",
                "wallet_id": wallet_id,
            },
        )

    def require_bootstrap_admin(self) -> None:
        """Allow only trusted bootstrap/admin environment keys."""
        if self.is_bootstrap_admin:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "admin_access_denied",
                "message": "This operation requires a bootstrap admin API key.",
            },
        )


async def get_auth_context(
    api_key: str | None = Security(api_key_header),
    authorization: Annotated[str | None, Header()] = None,
) -> AuthContext:
    """
    Validate credentials and return caller context.

    Checks in order:
    1. Authorization: Bearer <jwt> (modern, short-lived)
    2. X-API-Key header (legacy, long-lived keys)

    Settings are read per call, not from the module-level singleton: tests and
    the Postgres CI job rebind VALID_API_KEYS and clear the settings cache after
    this module is already imported, and a captured `settings` would keep
    serving the stale key list.
    """
    settings = get_settings()

    # A presented Authorization header is authoritative. Never fall back to a
    # concurrently supplied API key when its scheme, shape, or token is invalid:
    # doing so would let an invalid bearer credential authenticate as a different
    # principal than the caller intended.
    if authorization is not None:
        token = _parse_bearer_authorization(authorization)
        return await _auth_from_jwt(token)

    # Preserve the pre-header direct-call/X-API-Key compatibility path.
    if api_key and api_key.startswith("Bearer "):
        token = api_key[7:].strip()
        return await _auth_from_jwt(token)

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "missing_credentials",
                "message": "X-API-Key or Authorization: Bearer header is required.",
                "docs": "/docs",
            },
        )

    # RED TEAM FIX: Reject empty or whitespace-only keys.
    stripped = api_key.strip()
    if not stripped or len(stripped) < 8:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "invalid_api_key",
                "message": "API key must be at least 8 characters.",
            },
        )

    # Try JWT first (token might not start with "Bearer " but be a raw JWT)
    if stripped.count(".") == 2 and len(stripped) > 50:
        try:
            return await _auth_from_jwt(stripped)
        except Exception:
            pass  # Not a valid JWT, fall through to API key

    valid_keys = [k.strip() for k in settings.VALID_API_KEYS.split(",") if k.strip()]

    if any(hmac.compare_digest(stripped, key) for key in valid_keys):
        return AuthContext(
            source="env",
            raw_key=stripped,
            is_bootstrap_admin=True,
        )

    try:
        from ..services.api_key_service import get_api_key_service

        db_key = await get_api_key_service().validate_key(stripped)
    except RuntimeError:
        db_key = None

    if db_key:
        return AuthContext(
            source="db",
            raw_key=stripped,
            key_id=db_key.key_id,
            wallet_id=db_key.wallet_id,
            is_bootstrap_admin=False,
        )

    if valid_keys or not settings.DEBUG:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "invalid_api_key",
                "message": "The provided API key is not authorized.",
            },
        )

    if is_production_like_environment(settings.ENVIRONMENT):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "invalid_api_key",
                "message": "The provided API key is not authorized.",
            },
        )

    return AuthContext(
        source="env",
        raw_key=stripped,
        is_bootstrap_admin=True,
    )


def _parse_bearer_authorization(authorization: str) -> str:
    """Accept exactly ``Bearer <nonempty-token>`` with no extra whitespace."""
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        token = ""
    else:
        token = authorization[len(prefix) :]

    if not token or token != token.strip() or any(char.isspace() for char in token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "invalid_token",
                "message": "Authorization header must be exactly 'Bearer <token>'.",
            },
        )
    return token


async def _auth_from_jwt(token: str) -> AuthContext:
    """Verify JWT and return AuthContext."""
    from .jwt import get_jwt_service, JWTError

    jwt_svc = get_jwt_service()
    try:
        payload = jwt_svc.verify_access_token(token)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "invalid_token",
                "message": str(e),
            },
        ) from e

    if payload.key_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "unbound_access_token",
                "message": (
                    "This access token is not bound to an API key; authenticate "
                    "with an active API key."
                ),
            },
        )

    from ..services.api_key_service import get_api_key_service

    if not await get_api_key_service().is_key_live(payload.key_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "no_active_api_key",
                "message": (
                    "The API key that issued this access token is no longer active."
                ),
            },
        )

    return AuthContext(
        source="jwt",
        raw_key=token[:20] + "...",
        wallet_id=payload.sub,
        key_id=payload.key_id,
        is_bootstrap_admin=False,
        scopes=payload.scopes,
    )


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
) -> str:
    """
    Validate the provided API key.
    Returns the raw key on success for backwards-compatible dependencies.
    """
    context = await get_auth_context(api_key)
    return context.raw_key
