"""Per-key tool allowlists and the self-serve demo tenant.

A key may carry ``allowed_tools_json`` (NULL = unrestricted, ``[]`` = no
tools) plus a ``tenant`` label (NULL = normal, ``"demo"`` = self-serve demo
tenant). Both are populated onto ``AuthContext`` at authentication and
enforced at two choke points:

- permit creation (routers check BEFORE the idempotency record is begun;
  ``PermitService`` re-checks as defense in depth), and
- tool invoke (top of ``_execute_registered_tool_inner``, before any permit
  lookup, budget reservation, idempotency claim, charge, or dispatch).

Demo keys hold FULL permissions inside the demo tenant: by default they are
minted unrestricted and uncapped. Tenant containment always applies:

- permits: issuer and subject wallets must be in the same tenant whenever
  demo is involved (no cross-tenant permits either way, not even for
  bootstrap admins);
- money: the wallet engine refuses transfers/reclaims across tenants;
- routes: demo-tenant callers are confined by a short denylist covering
  real-money, cross-tenant, and admin surfaces, enforced where the
  credential is resolved (``app.core.auth`` reads the request path stashed
  by ``DemoRequestContextMiddleware`` below).

Each optional demo limit (tool allowlist, permit credit/TTL caps, key
expiry, use cap, wallet daily limit) is applied only when its setting is
set; None means that limit is off. The issuance abuse controls (per-IP and
global rate limits, live-key cap, Origin check, alerts) always apply.

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
    max_credits: Decimal,
    expires_at: datetime,
    caller_key_expires_at: datetime | None,
    demo_allowed_tools: list[str],
    max_permit_credits: Decimal | None,
    max_permit_ttl: timedelta | None,
    now: datetime,
) -> None:
    """Enforce demo-tenant containment plus whichever optional caps are set.

    Applies whenever the issuer wallet, the subject wallet, or the caller
    key is demo-tenant, regardless of who calls. The one unconditional rule
    is tenant containment: issuer and subject wallets must be in the SAME
    tenant — no cross-tenant permits in either direction, refused even for
    bootstrap admins. (Permit creation already requires the caller to own
    the issuer wallet, and invoke requires owning the charged wallet, so a
    demo key can never act on a normal wallet; this rule closes the
    permit-minting direction too.)

    Beyond that, a demo key is treated like a normal key: no demo-only bans
    on scopes, human approval, repeat windows, or action contracts. Each
    optional cap applies only when its setting is set (None = off):

    - ``demo_allowed_tools`` non-empty: the permit's tools must be a
      non-empty subset of it;
    - ``max_permit_credits`` set: ``max_credits`` must fit under it;
    - ``max_permit_ttl`` set: ``expires_at`` must fit inside it.

    A permit may never outlive the caller key's own expiry. Raises
    ``DemoPermitDenied`` naming the violated bound.
    """
    demo_involved = (
        issuer_tenant == DEMO_TENANT_LABEL
        or subject_tenant == DEMO_TENANT_LABEL
        or caller_tenant == DEMO_TENANT_LABEL
    )
    if not demo_involved:
        return
    if issuer_tenant != subject_tenant:
        raise DemoPermitDenied(
            "cross-tenant permits are forbidden: issuer and subject wallets "
            "must be in the same tenant"
        )
    if demo_allowed_tools:
        tools = list(allowed_tools or [])
        if not tools or any(t not in demo_allowed_tools for t in tools):
            raise DemoPermitDenied(
                "demo permit allowed_tools must be a non-empty subset of "
                f"{demo_allowed_tools}"
            )
    if max_permit_credits is not None and max_credits > max_permit_credits:
        raise DemoPermitDenied(
            f"demo permit max_credits {max_credits} exceeds the cap {max_permit_credits}"
        )
    # Naive-UTC normalize: request datetimes may carry tzinfo while stored
    # key expiries are naive UTC (see app.core.time.to_naive_utc).
    expires_naive = expires_at.replace(tzinfo=None)
    if (
        max_permit_ttl is not None
        and expires_naive > now.replace(tzinfo=None) + max_permit_ttl
    ):
        raise DemoPermitDenied("demo permit expires_at exceeds the demo TTL cap")
    if (
        caller_key_expires_at is not None
        and expires_naive > caller_key_expires_at.replace(tzinfo=None)
    ):
        raise DemoPermitDenied("demo permit cannot outlive the caller key's expiry")


def hash_client_id(client_id: str) -> str:
    """One-way hash for logs/counters: never store the raw IP or key."""
    return hashlib.sha256(client_id.encode("utf-8")).hexdigest()


# --- Demo route confinement (denylist) -----------------------------------

#: Path prefixes a demo-tenant credential may never call. Everything else a
#: wallet-scoped key could reach stays reachable: demo keys hold FULL
#: permissions inside the demo tenant, and wallet ownership (``AuthContext``)
#: plus the same-tenant permit/money rules already confine them to demo
#: wallets. This list covers only what ownership cannot: surfaces that move
#: fiat or settle externally, mint credentials outside the demo issuance
#: flow, manage trust-plane keys, or are inherently cross-tenant/admin.
#:
#: Most of these routers are not even mounted in production (dormant trust
#: surfaces and proof surfaces behind ``ENABLE_PROOF_SURFACES=false``) — the
#: entries still apply so mounting them later cannot open a hole.
#:
#: Matching is exact-or-slash-boundary: ``/v1/api-keys`` denies
#: ``/v1/api-keys`` and ``/v1/api-keys/...`` but not a hypothetical
#: ``/v1/api-keys2``.
_DEMO_DENIED_PREFIXES = (
    # Generic credential minting/rotation outside the demo self-service
    # endpoints below (a demo key must not mint siblings via /v1/api-keys;
    # is_key_bounded already refuses bounded minters, this is the route
    # backstop).
    "/v1/api-keys",
    # Second authentication story: nothing may mint Bearer [REDACTED] for demo wallets.
    "/v1/auth",
    # Fiat, external settlement, identity verification.
    "/v1/kyc",
    "/v1/x402",
    "/v1/billing/top-up",
    "/v1/billing/acp/checkout",
    "/v1/webhooks",
    # Wallet creation outside demo issuance (demo wallets come only from
    # POST /v1/demo/keys; children inherit the demo tenant anyway).
    "/v1/billing/wallets/sponsor",
    "/v1/billing/wallets/agent",
    "/v1/billing/wallets/child",
    # Named-group budgets spanning wallets: inherently cross-wallet.
    "/v1/pods",
    # Trust-plane signing keys and demo admin: tenant-boundary / admin.
    "/v1/signing-keys",
    "/v1/demo/admin",
)


def _demo_path_denied(path: str) -> bool:
    """True if no demo-tenant credential may call ``path`` (any method)."""
    for prefix in _DEMO_DENIED_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def demo_route_allowed(method: str, path: str) -> bool:
    """True if a demo-tenant key may call ``method path``.

    Denylist: everything is allowed except ``_DEMO_DENIED_PREFIXES``. Kept
    as a (method, path) wrapper so call sites read naturally and tests can
    probe the policy directly. ``method`` is currently unused — no denied
    surface has a method-scoped carve-out — and is kept so a future
    allow-this-verb exception does not change call sites.
    """
    del method
    return not _demo_path_denied(path)


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


async def resolve_effective_tenant(
    key_tenant: str | None, wallet_id: str | None
) -> str | None:
    """Tenant of a credential, fail-closed toward demo.

    A credential counts as demo-tenant if the KEY's tenant is "demo" OR the
    owning WALLET's tenant is "demo", so the kill switch and the denylist
    cannot be dodged by a key minted before tenant inheritance existed (or
    by any path that stamps the wallet but not the key). Tenant is a
    property of the wallet; the key label is a cached fast path.
    """
    if key_tenant == DEMO_TENANT_LABEL:
        return DEMO_TENANT_LABEL
    if not wallet_id:
        return key_tenant
    from app.db.database import get_session_factory
    from app.db.models import WalletModel

    factory = get_session_factory()
    async with factory() as session:
        wallet = await session.get(WalletModel, wallet_id)
        wallet_tenant = getattr(wallet, "tenant", None) if wallet else None
    if wallet_tenant == DEMO_TENANT_LABEL:
        return DEMO_TENANT_LABEL
    return key_tenant or wallet_tenant


# --- Issuance abuse controls ---------------------------------------------

#: Counter scopes for the unauthenticated issuance endpoint. The scope name
#: is the 429 body's ``scope`` field.
ISSUE_SCOPE_IP = "ip"
ISSUE_SCOPE_GLOBAL_HOUR = "global_hour"
ISSUE_SCOPE_GLOBAL_DAY = "global_day"
ISSUE_SCOPE_LIVE_KEYS = "live_keys"

_ISSUANCE_UNAVAILABLE = "demo_issuance_unavailable"
_ISSUANCE_RATE_LIMITED = "demo_issuance_rate_limited"

# In-process fallback counters: {counter_key: (count, expires_at_epoch)}.
# Used ONLY when REDIS_URL is unset, which production-like deployments with
# the demo tenant on refuse at boot — so this never guards real multi-replica
# traffic. Guarded by a lock; issuance is low-frequency.
_memory_counters: dict[str, tuple[int, float]] = {}
_memory_counters_lock: Any = None
# In-process alert dedup: {(scope, hour_bucket): True}.
_alerted_buckets: set[tuple[str, str]] = set()


def _counters_lock() -> Any:
    """Process-wide asyncio lock for the fallback counters (lazy)."""
    global _memory_counters_lock
    if _memory_counters_lock is None:
        import asyncio

        _memory_counters_lock = asyncio.Lock()
    return _memory_counters_lock


def _is_production_like() -> bool:
    from app.core.config import get_settings
    from app.core.trust_mode import is_production_like_environment

    return is_production_like_environment(get_settings().ENVIRONMENT)


async def _incr_counter(key: str, ttl_seconds: int) -> int | None:
    """Atomically increment a rate-limit counter; None when unavailable.

    Redis (shared across replicas) when REDIS_URL is set; the in-process
    fallback otherwise. Returns None only when Redis is configured but the
    increment failed — callers fail closed in production-like environments.
    """
    import time as _time

    from app.core.config import get_settings
    from app.core.rate_limiter import enforce_redis_timeouts

    redis_url = get_settings().REDIS_URL.strip()
    if redis_url:
        try:
            import redis.asyncio as redis

            client = enforce_redis_timeouts(redis.from_url(redis_url))
            try:
                count = int(await client.incr(key))
                if count == 1:
                    await client.expire(key, ttl_seconds)
                return count
            finally:
                try:
                    await client.aclose()
                except Exception:  # noqa: BLE001 - best-effort close
                    pass
        except Exception:  # noqa: BLE001 - Redis down: caller decides
            return None
    now = _time.time()
    async with _counters_lock():
        count, expires = _memory_counters.get(key, (0, 0.0))
        if expires <= now:
            count = 0
        count += 1
        _memory_counters[key] = (count, now + ttl_seconds)
        return count


async def check_issuance_limits(client_id: str) -> tuple[str | None, int | None]:
    """Check per-IP, global, and live-key issuance limits.

    Returns (scope, limit) of the first exhausted limit, else (None, None).
    Returns ("unavailable", None) when counters are unreachable in a
    production-like environment (fail closed with 503).
    """
    import datetime as _dt

    from app.core.config import get_settings

    settings = get_settings()
    ip_hash = hash_client_id(client_id)
    day = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    hour = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d-%H")

    checks = (
        (
            f"demo:issue:ip:{ip_hash}:{day}",
            24 * 3600,
            settings.DEMO_ISSUE_PER_IP_PER_DAY,
        ),
        (
            f"demo:issue:global-hour:{hour}",
            2 * 3600,
            settings.DEMO_ISSUE_GLOBAL_PER_HOUR,
        ),
        (
            f"demo:issue:global-day:{day}",
            2 * 24 * 3600,
            settings.DEMO_ISSUE_GLOBAL_PER_DAY,
        ),
    )
    scopes = (ISSUE_SCOPE_IP, ISSUE_SCOPE_GLOBAL_HOUR, ISSUE_SCOPE_GLOBAL_DAY)
    for (counter_key, ttl, limit), scope in zip(checks, scopes):
        count = await _incr_counter(counter_key, ttl)
        if count is None:
            if _is_production_like():
                return "unavailable", None
            continue
        if count > limit:
            return scope, limit
    live = await count_live_demo_keys()
    if live is None:
        if _is_production_like():
            return "unavailable", None
    elif live >= settings.DEMO_MAX_LIVE_KEYS:
        return ISSUE_SCOPE_LIVE_KEYS, settings.DEMO_MAX_LIVE_KEYS
    return None, None


async def count_live_demo_keys() -> int | None:
    """Count active, unexpired demo-tenant keys. None on DB failure."""
    try:
        from sqlalchemy import func, or_, select
        from sqlmodel import col

        from app.core.time import utc_now
        from app.db.database import get_session_factory
        from app.db.models import APIKeyModel

        now_naive = utc_now().replace(tzinfo=None)
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(func.count())
                .select_from(APIKeyModel)
                .where(
                    col(APIKeyModel.tenant) == DEMO_TENANT_LABEL,
                    col(APIKeyModel.status) == "active",
                    col(APIKeyModel.revoked_at).is_(None),
                    or_(
                        col(APIKeyModel.expires_at).is_(None),
                        col(APIKeyModel.expires_at) >= now_naive,
                    ),
                )
            )
            return int(result.scalar_one())
    except Exception:  # noqa: BLE001 - callers fail closed, never 500 here
        logger.warning("demo_count_live_keys_failed", exc_info=True)
        return None


async def count_recent_issues(hours: int) -> int:
    """Demo keys minted in the last ``hours`` hours (for stats/alerts)."""
    import datetime as _dt

    from sqlalchemy import func, select
    from sqlmodel import col

    from app.db.database import get_session_factory
    from app.db.models import APIKeyModel

    cutoff = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) - _dt.timedelta(
        hours=hours
    )
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(func.count())
            .select_from(APIKeyModel)
            .where(
                col(APIKeyModel.tenant) == DEMO_TENANT_LABEL,
                col(APIKeyModel.created_at) >= cutoff,
            )
        )
        return int(result.scalar_one())


async def maybe_send_demo_alert(scope: str, message: str) -> bool:
    """Send at most one alert per scope per hour. Returns True if sent.

    Alert failures never raise: alerting must not fail the request it
    reports on.
    """
    import datetime as _dt

    hour = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d-%H")
    if (scope, hour) in _alerted_buckets:
        return False
    _alerted_buckets.add((scope, hour))
    try:
        from app.services.notifications import get_notification_service

        await get_notification_service().send_security_alert(
            wallet_id="demo-tenant",
            alert_type=f"demo_issuance_{scope}",
            message=message,
        )
        return True
    except Exception:  # noqa: BLE001 - alerts never fail requests
        logger.warning("demo_alert_failed scope=%s", scope, exc_info=True)
        return False


async def mint_demo_keypair() -> dict[str, Any]:
    """Mint a fresh demo sponsor wallet + agent wallet + key, atomically.

    Both wallets carry tenant="demo" with synthetic, out-of-thin-air credit
    (``DEMO_WALLET_CREDITS``) — never drawn from a real wallet. The key
    carries the demo tool allowlist only when ``DEMO_ALLOWED_TOOLS`` is set
    (empty = unrestricted), plus whichever of the optional key bounds are
    set (None = no expiry / unlimited uses). Composed in one transaction
    (see app/services/pods.py): any failure rolls everything back, so a key
    whose wallets do not exist is never returned.
    """
    from uuid import uuid4

    from app.core.config import get_settings
    from app.db.database import get_session_factory
    from app.services.agent_money import get_agent_money
    from app.services.api_key_service import get_api_key_service

    settings = get_settings()
    money = get_agent_money()
    keys = get_api_key_service()
    agent_id = f"demo-{uuid4().hex[:8]}"
    demo_tools = settings.demo_allowed_tools_list

    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            sponsor = await money.create_sponsor_wallet(
                sponsor_name=f"demo-self-provision:{agent_id}",
                email=f"{agent_id}@demo.local",
                initial_credits=settings.DEMO_WALLET_CREDITS,
                require_kyc=False,
                tenant=DEMO_TENANT_LABEL,
                session=session,
            )
            agent = await money.create_agent_wallet(
                sponsor_wallet_id=sponsor.wallet_id,
                agent_id=agent_id,
                budget_credits=settings.DEMO_WALLET_CREDITS,
                daily_limit=settings.DEMO_WALLET_DAILY_LIMIT,
                session=session,
            )
            key = await keys.create_key(
                wallet_id=agent.wallet_id,
                key_name="self-provisioned-demo",
                expires_in_days=settings.DEMO_KEY_TTL_DAYS,
                max_uses=settings.DEMO_KEY_MAX_USES,
                allowed_tools=(demo_tools if demo_tools else None),
                tenant=DEMO_TENANT_LABEL,
                session=session,
            )
    return {
        "api_key": key["api_key"],
        "key_id": key["key_id"],
        "key_prefix": key["key_prefix"],
        "wallet_id": agent.wallet_id,
        "sponsor_wallet_id": sponsor.wallet_id,
        "tenant": DEMO_TENANT_LABEL,
        "allowed_tools": demo_tools if demo_tools else None,
        "expires_at": key["expires_at"],
        "max_uses": key["max_uses"],
        "budget_credits": settings.DEMO_WALLET_CREDITS,
    }


async def revoke_all_demo_keys() -> int:
    """Revoke every active demo-tenant key. Returns the revoked count."""
    from app.db.database import get_session_factory
    from app.db.models import APIKeyModel
    from app.core.time import utc_now

    from sqlalchemy import select
    from sqlmodel import col

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(APIKeyModel).where(
                col(APIKeyModel.tenant) == DEMO_TENANT_LABEL,
                col(APIKeyModel.status) == "active",
                col(APIKeyModel.revoked_at).is_(None),
            )
        )
        keys = list(result.scalars().all())
        now = utc_now()
        for row in keys:
            row.status = "revoked"
            row.revoked_at = now
            row.revoke_reason = "demo_admin_revoke_all"
        await session.commit()
        return len(keys)
