"""Scope enforcement decorator for FastAPI routes.

Usage:
    @router.post("/v1/permits")
    @require_scope("billing:charge")
    async def create_permit(...):
        ...
"""

from __future__ import annotations

from functools import wraps
from typing import Callable, TypeVar

from fastapi import HTTPException, status

from app.core.auth import AuthContext

#: Scope names the login endpoint (POST /v1/auth/token) may mint into a
#: token. Requested names outside this set are dropped at mint time, so a
#: caller cannot self-mint a permission that a scope-checked route would
#: later trust. Extend this set when a new scope-checked route ships.
ALLOWED_TOKEN_SCOPES = frozenset({"billing:charge", "tool:invoke"})

F = TypeVar("F", bound=Callable)


def intersect_token_scopes(requested: list[str]) -> list[str]:
    """Limit requested scopes to ALLOWED_TOKEN_SCOPES, keeping order.

    Unknown names are dropped (not rejected), and duplicates collapse, so
    the minted token carries only permissions the service itself grants.
    """
    kept: list[str] = []
    for scope in requested:
        if scope in ALLOWED_TOKEN_SCOPES and scope not in kept:
            kept.append(scope)
    return kept


def require_scope(*required_scopes: str) -> Callable[[F], F]:
    """Decorator that checks JWT scopes on the auth context.

    API key callers (source="db" or "env") bypass scope checks
    (they have implicit full access). JWT callers must have at least
    one of the required scopes.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> F:
            # Find AuthContext in kwargs
            auth: AuthContext | None = kwargs.get("auth")
            if auth is None:
                for arg in args:
                    if isinstance(arg, AuthContext):
                        auth = arg
                        break

            if auth is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={
                        "error": "unauthenticated",
                        "message": "Authentication required.",
                    },
                )

            # API key callers have implicit full access. "static-dev" is the
            # local-only static development/training key path; it carries
            # bootstrap-admin power in local-compatible environments only.
            if auth.source in ("db", "env", "static-dev"):
                return await func(*args, **kwargs)

            # JWT callers must have at least one required scope
            if not any(scope in auth.scopes for scope in required_scopes):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error": "insufficient_scope",
                        "message": f"Requires one of: {', '.join(required_scopes)}",
                        "required": list(required_scopes),
                        "provided": auth.scopes,
                    },
                )

            return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
