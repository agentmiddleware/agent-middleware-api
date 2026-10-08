"""Scope enforcement decorator for FastAPI routes.

Usage:
    @router.post("/v1/billing/charge")
    @require_scope("billing:charge")
    async def charge_wallet(...):
        ...

Enforced today on POST /v1/billing/charge ("billing:charge"). API key
callers (source "db", "env", "static-dev") bypass scope checks; JWT callers
must carry one of the required scopes. Extending this to permit issuance
and tool invoke routes needs a wider scope vocabulary first.
"""

from __future__ import annotations

from functools import wraps
from typing import Callable, TypeVar

from fastapi import HTTPException, status

from app.core.auth import AuthContext

F = TypeVar("F", bound=Callable)


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
