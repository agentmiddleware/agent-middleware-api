"""Per-key tool allowlists and the self-serve demo tenant.

A key may carry ``allowed_tools_json`` (NULL = unrestricted, ``[]`` = no
tools) plus a ``tenant`` label (NULL = normal, ``"demo"`` = self-serve demo
tenant). Both are populated onto ``AuthContext`` at authentication and
enforced at two choke points:

- permit creation (routers check BEFORE the idempotency record is begun;
  ``PermitService`` re-checks as defense in depth), and
- tool invoke (top of ``_execute_registered_tool_inner``, before any permit
  lookup, budget reservation, idempotency claim, charge, or dispatch).

Demo-tenant callers are additionally confined to a route allowlist, enforced
where the credential is resolved (``app.core.auth`` reads the request path
stashed by ``DemoRequestContextMiddleware`` below), and demo permits are
capped whenever the issuer wallet, the subject wallet, or the caller key is
demo-tenant.

Everything here is default-off: with no allowlists set and
``ENABLE_DEMO_TENANT=false``, no check triggers.
"""

from __future__ import annotations

import hashlib
import json
import logging
from contextvars import ContextVar
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("app.demo_tenant")

DEMO_TENANT_LABEL = "demo"

KEY_TOOL_NOT_ALLOWED = "key_tool_not_allowed"
DEMO_PERMIT_OUT_OF_BOUNDS = "demo_permit_out_of_bounds"
DEMO_KEY_ROUTE_FORBIDDEN = "demo_key_route_forbidden"
DEMO_TENANT_DISABLED = "demo_tenant_disabled"


class KeyAllowlistDenied(Exception):
    """A permit request exceeds the caller key's tool allowlist."""

    def __init__(self, message: str):
        super().__init__(message)
        self.error = KEY_TOOL_NOT_ALLOWED
        self.message = message


class DemoPermitDenied(Exception):
    """A permit request exceeds the demo tenant caps."""

    def __init__(self, message: str):
        super().__init__(message)
        self.error = DEMO_PERMIT_OUT_OF_BOUNDS
        self.message = message


def parse_allowlist(raw: str | None) -> tuple[str, ...] | None:
    """Parse a stored allowlist: NULL -> None (unrestricted).

    A corrupt value fails closed to an empty allowlist (no tools), never to
    unrestricted.
    """
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ()
    if not isinstance(parsed, list) or not all(
        isinstance(item, str) for item in parsed
    ):
        return ()
    return tuple(parsed)


def effective_permit_scopes(
    scopes: list[str] | None, allowed_tools: list[str] | None
) -> list[str]:
    """Mirror the permit service's scope defaulting for pre-checks.

    ``PermitService._persist_permit`` derives ``tool:<t>:invoke`` scopes from
    ``allowed_tools`` when no explicit scopes are given and always adds
    ``billing:charge``. Enforcement must judge the effective scopes, not just
    the request body, or an empty ``scopes`` list would dodge the check while
    the persisted permit still authorizes the tools.
    """
    derived = list(scopes or [])
    if not derived:
        derived = [f"tool:{tool}:invoke" for tool in (allowed_tools or [])]
    if "billing:charge" not in derived:
        derived = [*derived, "billing:charge"]
    return derived


def _tool_scope_name(scope: str) -> str | None:
    """Return the tool name for ``tool:<name>:<action>`` scopes, else None."""
    parts = scope.split(":")
    if len(parts) >= 3 and parts[0] == "tool" and parts[1]:
        return parts[1]
    return None


def check_key_allowlist_for_permit(
    *,
    key_allowlist: tuple[str, ...] | None,
    allowed_tools: list[str] | None,
    scopes: list[str] | None,
) -> None:
    """Enforce a key's tool allowlist on a permit request.

    Raises ``KeyAllowlistDenied`` before any idempotency record is begun or
    any permit is signed. A ``None`` allowlist is unrestricted (all existing
    keys) and returns silently.
    """
    if key_allowlist is None:
        return
    tools = list(allowed_tools or [])
    if not tools:
        # An empty permit allowlist must not mean "all tools" for a key that
        # opted into a list: refuse whatever would broaden.
        raise KeyAllowlistDenied(
            "permit allowed_tools must be non-empty for a key with a tool allowlist"
        )
    for tool in tools:
        if tool == "*" or tool not in key_allowlist:
            raise KeyAllowlistDenied(
                f"permit tool {tool!r} is not in this key's allowlist"
            )
    for scope in effective_permit_scopes(scopes, tools):
        if scope == "billing:charge":
            continue
        name = _tool_scope_name(scope)
        if name is None:
            raise KeyAllowlistDenied(
                f"permit scope {scope!r} is not a recognized tool scope"
            )
        if name == "*" or name not in key_allowlist:
            raise KeyAllowlistDenied(
                f"permit scope {scope!r} names a tool outside this key's allowlist"
            )


def check_demo_permit_bounds(
    *,
    issuer_tenant: str | None,
    subject_tenant: str | None,
    caller_tenant: str | None,
    allowed_tools: list[str] | None,
    scopes: list[str] | None,
    max_credits: Decimal,
    expires_at: datetime,
    caller_key_expires_at: datetime | None,
    requires_human_approval: bool,
    repeat_window_seconds: int | None,
    action_contract_version: int | None,
    demo_allowed_tools: list[str],
    max_permit_credits: Decimal,
    max_permit_ttl: timedelta,
    now: datetime,
) -> None:
    """Enforce demo permit caps.

    Applies whenever the issuer wallet, the subject wallet, or the caller
    key is demo-tenant, regardless of who calls. Cross-tenant permits are
    refused even for bootstrap admins: keep it simple and strict. Raises
    ``DemoPermitDenied`` naming the violated bound.
    """
    demo_involved = (
        issuer_tenant == DEMO_TENANT_LABEL
        or subject_tenant == DEMO_TENANT_LABEL
        or caller_tenant == DEMO_TENANT_LABEL
    )
    if not demo_involved:
        return
    if issuer_tenant != DEMO_TENANT_LABEL or subject_tenant != DEMO_TENANT_LABEL:
        raise DemoPermitDenied(
            "demo permits require both issuer and subject wallets to be demo-tenant"
        )
    if action_contract_version is not None:
        raise DemoPermitDenied("demo permits cannot carry an action contract")
    if requires_human_approval:
        raise DemoPermitDenied("demo permits cannot require human approval")
    if repeat_window_seconds is not None:
        raise DemoPermitDenied("demo permits cannot set repeat_window_seconds")
    tools = list(allowed_tools or [])
    if not tools or any(t not in demo_allowed_tools for t in tools):
        raise DemoPermitDenied(
            f"demo permit allowed_tools must be a non-empty subset of {demo_allowed_tools}"
        )
    allowed_scopes = {f"tool:{tool}:invoke" for tool in tools} | {"billing:charge"}
    for scope in effective_permit_scopes(scopes, tools):
        if scope not in allowed_scopes:
            raise DemoPermitDenied(
                f"demo permit scope {scope!r} is outside the demo scope set"
            )
    if max_credits > max_permit_credits:
        raise DemoPermitDenied(
            f"demo permit max_credits {max_credits} exceeds the cap {max_permit_credits}"
        )
    # Naive-UTC normalize: request datetimes may carry tzinfo while stored
    # key expiries are naive UTC (see app.core.time.to_naive_utc).
    expires_naive = expires_at.replace(tzinfo=None)
    if expires_naive > now.replace(tzinfo=None) + max_permit_ttl:
        raise DemoPermitDenied("demo permit expires_at exceeds the demo TTL cap")
    if (
        caller_key_expires_at is not None
        and expires_naive > caller_key_expires_at.replace(tzinfo=None)
    ):
        raise DemoPermitDenied("demo permit cannot outlive the caller key's expiry")


def hash_client_id(client_id: str) -> str:
    """One-way hash for logs/counters: never store the raw IP or key."""
    return hashlib.sha256(client_id.encode("utf-8")).hexdigest()


# --- Demo route confinement -----------------------------------------------

#: Exact (method, path) grants for demo-tenant keys.
_DEMO_ALLOWED_EXACT = frozenset(
    {
        ("POST", "/v1/permits"),
        ("POST", "/v1/permits/verify"),
        ("POST", "/mcp/messages"),
        ("POST", "/mcp"),
        ("GET", "/mcp/tools"),
        ("GET", "/mcp/tools.json"),
        ("GET", "/v1/me"),
        ("POST", "/v1/demo/keys"),
        ("POST", "/v1/demo/keys/rotate"),
        ("POST", "/v1/demo/keys/revoke"),
    }
)


def _demo_path_allowed(method: str, path: str) -> bool:
    """True if a demo-tenant key may call ``method path``.

    Exact matches cover fixed routes; the two parameterized families are
    matched by segment shape so a demo key reaches exactly the permit,
    permit-receipt, receipt, and portable-receipt reads the launch needs —
    and nothing else (no permit revoke, no receipt list/verify, no /v1/me
    sub-routes, no wallet or billing surfaces).
    """
    if (method, path) in _DEMO_ALLOWED_EXACT:
        return True
    if method == "GET":
        segments = [seg for seg in path.split("/") if seg]
        if (
            len(segments) == 3
            and segments[0] == "v1"
            and segments[1] == "permits"
            and segments[2]
        ):
            return True  # GET /v1/permits/{id}
        if (
            len(segments) == 4
            and segments[0] == "v1"
            and segments[1] == "permits"
            and segments[2]
            and segments[3] == "receipts"
        ):
            return True  # GET /v1/permits/{id}/receipts
        if (
            len(segments) == 3
            and segments[0] == "v1"
            and segments[1] == "receipts"
            and segments[2]
        ):
            return True  # GET /v1/receipts/{id}
        if (
            len(segments) == 4
            and segments[0] == "v1"
            and segments[1] == "receipts"
            and segments[2]
            and segments[3] == "portable"
        ):
            return True  # GET /v1/receipts/{id}/portable
        if (
            len(segments) == 3
            and segments[0] == "mcp"
            and segments[1] == "tools"
            and segments[2]
        ):
            return True  # GET /mcp/tools/{id}
    if method == "POST" and path.startswith("/mcp/tools/") and path.endswith("/invoke"):
        return True  # POST /mcp/tools/{id}/invoke
    return False


def demo_route_allowed(method: str, path: str) -> bool:
    """Public wrapper for the demo route allowlist (also used by tests)."""
    return _demo_path_allowed(method.upper(), path)


#: The (method, path) of the request currently being authenticated. Set by
#: ``DemoRequestContextMiddleware`` for every request so ``get_auth_context``
#: can confine demo-tenant credentials without changing its signature (it is
#: also called without a request, where the value stays None and demo keys
#: fail closed).
_demo_request: ContextVar[tuple[str, str] | None] = ContextVar(
    "demo_request", default=None
)


def current_demo_request() -> tuple[str, str] | None:
    """Return the (method, path) stashed for this request, if any."""
    return _demo_request.get()


class DemoRequestContextMiddleware(BaseHTTPMiddleware):
    """Stash (method, path) for auth-time demo route confinement.

    No authentication, no branching, negligible cost: the demo checks read
    this value and every other caller is unaffected.
    """

    async def dispatch(self, request, call_next):
        token = _demo_request.set((request.method, request.url.path))
        try:
            return await call_next(request)
        finally:
            _demo_request.reset(token)


def log_demo_event(event: str, **fields: Any) -> None:
    """Structured demo-tenant log line. Callers pass hashed IPs and key ids
    only — never the raw key or the raw IP."""
    parts = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info("%s %s", event, parts)
