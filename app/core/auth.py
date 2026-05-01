"""
API Key authentication for agent consumers.
Agents pass their key via the X-API-Key header. No cookies, no sessions,
no OAuth dance — just a key and a handshake.
"""

from dataclasses import dataclass

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from .config import get_settings

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

    def require_wallet_access(self, wallet_id: str) -> None:
        """Allow bootstrap admins or the exact wallet owning a DB-backed key."""
        if self.is_bootstrap_admin:
            return
        if self.wallet_id == wallet_id:
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
) -> AuthContext:
    """
    Validate an API key and return caller context.

    Environment keys are trusted bootstrap/admin credentials. If the key
    is not an environment key, fall through to the DB-backed key registry.
    """
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "missing_api_key",
                "message": "X-API-Key header is required.",
                "docs": "/docs",
            },
        )

    # RED TEAM FIX: Reject empty or whitespace-only keys.
    # FastAPI's APIKeyHeader passes empty strings through — a gap
    # that would let any request with `X-API-Key: ""` bypass auth.
    stripped = api_key.strip()
    if not stripped or len(stripped) < 8:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "invalid_api_key",
                "message": "API key must be at least 8 characters.",
            },
        )

    valid_keys = [k.strip() for k in settings.VALID_API_KEYS.split(",") if k.strip()]

    if stripped in valid_keys:
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

    # Development mode with no configured keys: preserve the previous local
    # testing behavior while still identifying the caller as bootstrap-scoped.
    return AuthContext(
        source="env",
        raw_key=stripped,
        is_bootstrap_admin=True,
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
