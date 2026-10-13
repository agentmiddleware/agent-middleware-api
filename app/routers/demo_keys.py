"""Self-serve demo tenant (Product Hunt launch).

``POST /v1/demo/keys`` lets an anonymous visitor mint their own demo agent
(sponsor wallet + agent wallet + wallet-scoped API key, all tenant="demo")
with no pre-shared secret, so they can run the permit → invoke → receipt
loop end to end on their own.

How it differs from ``app/routers/dev_keys.py`` (local-only self-provision):

- This endpoint IS allowed in production-like environments: it is gated by
  its own kill switch (``ENABLE_DEMO_TENANT``, default off) instead of the
  environment. When the flag is off the issuance route answers 404 AND every
  existing demo-tenant credential is refused at authentication
  (``demo_tenant_disabled``) — flipping the flag off instantly disables all
  demo traffic.
- Production-like + flag on requires ``REDIS_URL`` at boot (see
  ``validate_trust_mode_guardrails``): the issuance limits below must be
  shared across replicas. Without Redis the in-process fallback applies
  only to non-production-like environments; a Redis outage in
  production-like answers 503 rather than minting uncounted keys.
- Abuse controls protect signup (not the key): per-IP/day, global
  hour/day, and concurrent-live-key caps; an Origin check mirroring
  dev_keys so a third-party page cannot farm keys through visitors'
  browsers; structured logs plus a deduplicated Slack/email alert when the
  global hourly limit, the live-key cap, or the hourly issuance threshold
  is hit. Alert failures never fail the request.

Demo keys hold FULL permissions inside the demo tenant (unrestricted tools,
no permit caps, no expiry, no use cap by default — each can be turned back
on with its ``DEMO_*`` setting). Containment is structural: tenant is a
property of the wallet (inherited at creation, stamped onto keys at
creation, resolved fail-closed at authentication), permits and money
movement refuse cross-tenant pairs, and a short route denylist keeps demo
callers off fiat, credential-minting, and admin surfaces. See
docs/demo-tenant.md.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..core.auth import AuthContext, get_auth_context
from ..core.config import get_settings
from ..core.rate_limiter import _client_id
from ..services.api_key_service import KeyNotFoundError, get_api_key_service
from ..services.demo_tenant import (
    DEMO_TENANT_LABEL,
    ISSUE_SCOPE_GLOBAL_HOUR,
    ISSUE_SCOPE_IP,
    ISSUE_SCOPE_LIVE_KEYS,
    _ISSUANCE_RATE_LIMITED,
    _ISSUANCE_UNAVAILABLE,
    check_issuance_limits,
    count_live_demo_keys,
    count_recent_issues,
    hash_client_id,
    log_demo_event,
    maybe_send_demo_alert,
    mint_demo_keypair,
    revoke_all_demo_keys,
)

router = APIRouter(
    prefix="/v1/demo",
    tags=["Demo"],
)


class DemoKeyIssueResponse(BaseModel):
    """A freshly minted demo credential. The secret is shown once."""

    api_key: str = Field(description="Demo API key (shown once; store it now).")
    key_id: str
    key_prefix: str
    wallet_id: str = Field(description="Demo agent wallet backing this key.")
    sponsor_wallet_id: str
    tenant: str = DEMO_TENANT_LABEL
    allowed_tools: list[str] | None = Field(
        default=None,
        description="Tool allowlist, or null for unrestricted (default).",
    )
    expires_at: datetime | None = None
    max_uses: int | None = Field(
        default=None, description="Use cap, or null for unlimited (default)."
    )
    budget_credits: Decimal
    base_url: str = Field(description="API base URL hint for SDK callers.")
    note: str


class DemoKeyRotateResponse(BaseModel):
    """Replacement demo credential. The secret is shown once."""

    api_key: str
    key_id: str
    key_prefix: str
    wallet_id: str
    tenant: str = DEMO_TENANT_LABEL
    expires_at: datetime | None = None
    max_uses: int | None = None
    note: str


class DemoRevokeResponse(BaseModel):
    revoked_key_id: str


class DemoAdminRevokeAllResponse(BaseModel):
    revoked_count: int


class DemoAdminStatsResponse(BaseModel):
    live_demo_keys: int
    issued_last_hour: int
    issued_last_day: int


def _require_enabled() -> None:
    if not get_settings().ENABLE_DEMO_TENANT:
        raise HTTPException(status_code=404, detail="Not Found")


def _reject_cross_origin(request: Request) -> None:
    """Reject browser minting from origins the operator did not allow.

    Mirrors ``dev_keys._reject_cross_origin``, except the allowlist is
    operator-configured (``DEMO_ALLOWED_ORIGINS``): empty means only
    no-Origin callers (CLI/SDK/curl) and same-host pages may mint, so a
    third-party page cannot farm keys through visitors' browsers.
    """
    origin = request.headers.get("origin")
    if not origin:
        return
    origin_host = urlsplit(origin).hostname
    allowed = {request.url.hostname}
    public_url = get_settings().PUBLIC_URL
    if public_url:
        allowed.add(urlsplit(public_url).hostname)
    for entry in get_settings().DEMO_ALLOWED_ORIGINS.split(","):
        host = _allowed_origin_host(entry)
        if host:
            allowed.add(host)
    if origin_host not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "origin_not_allowed",
                "message": (
                    "Cross-origin browser requests are not accepted on this "
                    "endpoint. Call it from a CLI, SDK, or server-side client."
                ),
            },
        )


def _allowed_origin_host(entry: str) -> str | None:
    """Normalize a DEMO_ALLOWED_ORIGINS entry to a hostname.

    Accepts bare hosts (``app.example``, ``app.example:3000``) and full
    origins (``https://app.example``); comparison is always hostname to
    hostname.
    """
    entry = entry.strip()
    if not entry:
        return None
    if "://" not in entry:
        entry = "https://" + entry
    return urlsplit(entry).hostname


def _require_demo_caller(auth: AuthContext) -> None:
    """Only demo-tenant credentials may use the self-service endpoints."""
    if auth.tenant != DEMO_TENANT_LABEL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "demo_key_required",
                "message": "This endpoint is only available to demo-tenant keys.",
            },
        )


@router.post(
    "/keys",
    response_model=DemoKeyIssueResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Mint a self-serve demo key (anonymous)",
    description=(
        "Mint a demo sponsor wallet, agent wallet, and wallet-scoped API key "
        "with no pre-shared secret. Requires ENABLE_DEMO_TENANT. The key is "
        "shown once. Rate-limited per IP and globally."
    ),
)
async def issue_demo_key(request: Request) -> DemoKeyIssueResponse:
    _require_enabled()
    _reject_cross_origin(request)
    settings = get_settings()
    client_id = _client_id(request)
    ip_hash = hash_client_id(client_id)

    scope, limit = await check_issuance_limits(client_id)
    if scope == "unavailable":
        log_demo_event("demo_issue_unavailable", ip_hash=ip_hash)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": _ISSUANCE_UNAVAILABLE,
                "message": (
                    "Demo issuance is temporarily unavailable. Try again shortly."
                ),
            },
        )
    if scope is not None:
        log_demo_event(
            "demo_issue_rate_limited", scope=scope, limit=limit, ip_hash=ip_hash
        )
        if scope in (ISSUE_SCOPE_GLOBAL_HOUR, ISSUE_SCOPE_LIVE_KEYS):
            await maybe_send_demo_alert(
                scope,
                f"Demo issuance {scope} limit hit (limit {limit}).",
            )
        raise HTTPException(
            status_code=429,
            detail={"error": _ISSUANCE_RATE_LIMITED, "scope": scope},
            headers={"Retry-After": "3600" if scope != ISSUE_SCOPE_IP else "86400"},
        )

    minted = await mint_demo_keypair()
    log_demo_event(
        "demo_key_issued",
        key_id=minted["key_id"],
        wallet_id=minted["wallet_id"],
        ip_hash=ip_hash,
    )
    if scope is None:
        issued_hour = await count_recent_issues(1)
        if issued_hour >= settings.DEMO_ALERT_ISSUES_PER_HOUR:
            await maybe_send_demo_alert(
                "issues_per_hour",
                f"Demo issuance crossed {settings.DEMO_ALERT_ISSUES_PER_HOUR}/hour "
                f"(now {issued_hour}).",
            )
    base_url = settings.PUBLIC_URL.rstrip("/") if settings.PUBLIC_URL else ""
    return DemoKeyIssueResponse(
        api_key=minted["api_key"],
        key_id=minted["key_id"],
        key_prefix=minted["key_prefix"],
        wallet_id=minted["wallet_id"],
        sponsor_wallet_id=minted["sponsor_wallet_id"],
        tenant=minted["tenant"],
        allowed_tools=minted["allowed_tools"],
        expires_at=minted["expires_at"],
        max_uses=minted["max_uses"],
        budget_credits=minted["budget_credits"],
        base_url=base_url,
        note=(
            "Store the api_key now; it is shown only once. This key is "
            "confined to the demo tenant: it can only ever act on "
            "demo-tenant wallets, and flipping ENABLE_DEMO_TENANT off "
            "disables it instantly."
        ),
    )


@router.post(
    "/keys/rotate",
    response_model=DemoKeyRotateResponse,
    summary="Rotate your own demo key",
    description=(
        "Issue a replacement demo key inheriting the same expiry, remaining "
        "uses, allowlist, and tenant; the old key is revoked immediately. "
        "Only demo-tenant keys may use it."
    ),
)
async def rotate_demo_key(
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
) -> DemoKeyRotateResponse:
    _require_enabled()
    _require_demo_caller(auth)
    client_ip = request.client.host if request.client else None
    service = get_api_key_service()
    try:
        result = await service.rotate_key(
            wallet_id=auth.wallet_id or "",
            key_id=auth.key_id,
            revoke_old=True,
            reason="demo_self_rotate",
            triggered_by="user",
            ip_address=client_ip,
        )
    except KeyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    new_key = result["new_key"]
    log_demo_event(
        "demo_key_rotated",
        old_key_id=auth.key_id,
        key_id=new_key["key_id"],
    )
    return DemoKeyRotateResponse(
        api_key=new_key["api_key"],
        key_id=new_key["key_id"],
        key_prefix=new_key["key_prefix"],
        wallet_id=new_key["wallet_id"],
        tenant=DEMO_TENANT_LABEL,
        expires_at=new_key["expires_at"],
        max_uses=new_key["max_uses"],
        note="The previous key was revoked immediately. Store the api_key now.",
    )


@router.post(
    "/keys/revoke",
    response_model=DemoRevokeResponse,
    summary="Revoke your own demo key",
    description="Immediately revoke the calling demo key.",
)
async def revoke_demo_key(
    auth: AuthContext = Depends(get_auth_context),
) -> DemoRevokeResponse:
    _require_enabled()
    _require_demo_caller(auth)
    await get_api_key_service().revoke_key(
        auth.wallet_id or "", auth.key_id or "", "demo_self_revoke"
    )
    log_demo_event("demo_key_revoked", key_id=auth.key_id)
    return DemoRevokeResponse(revoked_key_id=auth.key_id or "")


def _require_bootstrap_admin(auth: AuthContext) -> None:
    auth.require_bootstrap_admin()


@router.post(
    "/admin/keys/{key_id}/revoke",
    response_model=DemoRevokeResponse,
    summary="Admin: revoke one demo key (bootstrap only)",
    description="Revoke a single tenant=demo key. 404 for any non-demo key.",
)
async def admin_revoke_demo_key(
    key_id: str,
    auth: AuthContext = Depends(get_auth_context),
) -> DemoRevokeResponse:
    # Admin cleanup works with the kill switch OFF too, so an operator can
    # revoke demo keys for good before re-enabling the tenant.
    _require_bootstrap_admin(auth)
    row = await get_api_key_service().get_key_record(key_id)
    if row is None or getattr(row, "tenant", None) != DEMO_TENANT_LABEL:
        raise HTTPException(status_code=404, detail="Not Found")
    await get_api_key_service().revoke_key(row.wallet_id, key_id, "demo_admin_revoke")
    log_demo_event("demo_key_admin_revoked", key_id=key_id)
    return DemoRevokeResponse(revoked_key_id=key_id)


@router.post(
    "/admin/revoke-all",
    response_model=DemoAdminRevokeAllResponse,
    summary="Admin: revoke every demo key (bootstrap only)",
    description=("Revoke all active demo-tenant keys at once. Returns the count."),
)
async def admin_revoke_all_demo_keys(
    auth: AuthContext = Depends(get_auth_context),
) -> DemoAdminRevokeAllResponse:
    # Admin cleanup works with the kill switch OFF too, so an operator can
    # revoke demo keys for good before re-enabling the tenant.
    _require_bootstrap_admin(auth)
    count = await revoke_all_demo_keys()
    log_demo_event("demo_keys_admin_revoke_all", revoked_count=count)
    return DemoAdminRevokeAllResponse(revoked_count=count)


@router.get(
    "/admin/stats",
    response_model=DemoAdminStatsResponse,
    summary="Admin: demo tenant stats (bootstrap only)",
)
async def admin_demo_stats(
    auth: AuthContext = Depends(get_auth_context),
) -> DemoAdminStatsResponse:
    # Admin cleanup works with the kill switch OFF too, so an operator can
    # revoke demo keys for good before re-enabling the tenant.
    _require_bootstrap_admin(auth)
    live = await count_live_demo_keys()
    return DemoAdminStatsResponse(
        live_demo_keys=live or 0,
        issued_last_hour=await count_recent_issues(1),
        issued_last_day=await count_recent_issues(24),
    )
