"""
API Key authentication for agent consumers.
Agents pass their key via the X-API-Key header. No cookies, no sessions,
no OAuth dance — just a key and a handshake.
"""

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from .config import get_settings

settings = get_settings()

api_key_header = APIKeyHeader(
    name=settings.API_KEY_HEADER,
    auto_error=False,
    description="API key for agent authentication. Pass in the X-API-Key header.",
)


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
) -> str:
    """
    Validate the provided API key against the allow-list.
    Returns the key on success so downstream handlers can use it
    for per-key rate limiting or usage tracking.
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

    if not valid_keys:
        # SECURITY FIX: Fail-safe for production.
        # If VALID_API_KEYS is unset/empty AND we're not in dev mode,
        # reject all requests. This prevents accidental open auth in production.
        if not settings.DEBUG:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "auth_not_configured",
                    "message": (
                        "API keys not configured. Set VALID_API_KEYS environment variable "
                        "or enable DEBUG=true for development."
                    ),
                },
            )
        # Development mode — accept any key ≥8 chars (for local testing)
        return stripped

    if stripped not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "invalid_api_key",
                "message": "The provided API key is not authorized.",
            },
        )

    return stripped
