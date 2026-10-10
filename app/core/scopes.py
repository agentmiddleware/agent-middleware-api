"""Scope enforcement decorator for FastAPI routes.

Usage:
    @router.post("/v1/permits")
    @require_scope("billing:charge")
    async def create_permit(...):
        ...
"""

from __future__ import annotations

import re
from functools import wraps
from typing import Callable, TypeVar

from fastapi import HTTPException, status

from app.core.auth import AuthContext

F = TypeVar("F", bound=Callable)

# Canonical scope vocabulary for JWT access tokens minted at /v1/auth/token.
# API keys carry no per-key scope restrictions (require_scope below grants
# key callers implicit full access), so every key is entitled to the same
# set: the exact names here plus the tool-invocation pattern. Anything else
# a caller asks for is not granted. If per-key entitlements are added later,
# intersect with them here as well.
KNOWN_SCOPES = frozenset(
    {
        # Default token scopes and the spend-gating scope permits require.
        "billing:charge",
        # Read-only billing scope used for limited tokens.
        "billing:read",
        # Generic tool-invocation scope (one of the defaults).
        "tool:invoke",
    }
)

# Tool-specific invocation scopes, e.g. "tool:partner.notes.write:invoke".
# This is the documented permit/tool pattern (see docs/quickstart.md), so a
# token minted for one governed tool cannot be widened by inventing names
# outside it.
_TOOL_SCOPE_RE = re.compile(r"^tool:[A-Za-z0-9_.\-]+:invoke$")


def is_known_scope(scope: str) -> bool:
    """Return True when ``scope`` is part of the grantable vocabulary."""
    return scope in KNOWN_SCOPES or _TOOL_SCOPE_RE.fullmatch(scope) is not None


def unknown_scopes(scopes: list[str]) -> list[str]:
    """Return the requested scopes that cannot be granted, in order."""
    return [scope for scope in scopes if not is_known_scope(scope)]


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
