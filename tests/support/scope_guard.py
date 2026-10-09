"""Test-only scope guard for JWT attenuation tests.

This is a test harness, NOT production authorization: no production module
may import it (see tests/test_scopes_removed.py). It mirrors the scope
semantics the deleted ``app.core.scopes.require_scope`` helper enforced so
the JWT authority tests keep a guarded endpoint to exercise:

- API key callers (source "db", "env", or "static-dev") pass through.
- JWT callers must carry at least one of the required scopes.
"""

from __future__ import annotations

from functools import wraps
from typing import Callable, TypeVar

from fastapi import HTTPException, status

from app.core.auth import AuthContext

F = TypeVar("F", bound=Callable)


def require_test_scope(*required_scopes: str) -> Callable[[F], F]:
    """Test-only decorator checking JWT scopes on the auth context."""

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> F:
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

            if auth.source in ("db", "env", "static-dev"):
                return await func(*args, **kwargs)

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
