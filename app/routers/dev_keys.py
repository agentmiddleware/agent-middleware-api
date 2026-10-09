"""Self-serve development key provisioning (local only, opt-in).

``POST /v1/dev-keys/self-provision`` lets an agent working against a local
instance mint its own wallet-scoped API key with no pre-shared secret. It
provisions the same shape ``scripts/partner_api_key_bootstrap.py`` produces
with a bootstrap admin — sponsor wallet → agent wallet → DB-backed key — so
self-served agents exercise the real credential class, not a special one.

Local-only by four independent layers, mirroring STATIC_DEV_API_KEYS:

- ``ENABLE_DEV_KEY_SELF_PROVISION`` defaults false and the route answers 404
  until an operator turns it on, so the surface is never advertised by
  accident (same pattern as ``ENABLE_STANDARD_MCP_ENDPOINT``).
- Production-like environments refuse to boot with the flag set
  (``validate_trust_mode_guardrails``), and the handler independently fails
  closed with 403 there, so the endpoint stays unreachable in production
  even if the boot gate were bypassed.
- A cross-origin ``Origin`` header is rejected (403). The endpoint takes no
  auth and returns a live secret in its body, so under the default wildcard
  CORS a page the developer merely visits could otherwise ``fetch`` this
  route against ``localhost`` and read the minted key cross-origin (a
  browser confused-deputy). Real dev agents — CLIs, SDKs, curl — send no
  ``Origin`` and pass through; only browser script from a foreign origin is
  refused. Same DNS-rebinding hardening the standard MCP endpoint uses.
- Each client address gets a bounded mint budget (429 past
  ``MAX_SELF_PROVISION_MINTS_PER_CLIENT`` mints per
  ``SELF_PROVISION_MINT_WINDOW_SECONDS``), enforced in the handler so the
  test-key rate-limit bypass cannot skip it. Forwarding headers are ignored
  when naming the budget, so rotating headers cannot rotate the budget.

The minted key is wallet-scoped, never bootstrap-admin: a credential anyone
can mint must not read the audit plane or touch other tenants' wallets. The
sponsor's credits are synthetic dev credits, bounded per call so a runaway
loop cannot mint an absurd balance. See docs/static-dev-api-keys.md.
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..core.config import get_settings
from ..core.trust_mode import is_production_like_environment
from ..services.agent_money import get_agent_money
from ..services.api_key_service import get_api_key_service

router = APIRouter(
    prefix="/v1/dev-keys",
    tags=["Development"],
)

MAX_BUDGET_CREDITS = Decimal("100000")

# Per-address cap on successful mints. The global request rate limiter alone
# cannot bound this route: one party rotating credentials gets a fresh budget
# per rotation, so without a per-client mint budget a single dev instance
# could be made to mint wallets without end. Ten per hour per client address
# is generous for local development (a developer mints a key per agent run)
# while keeping a runaway loop bounded. Deliberately in-memory: this endpoint
# refuses to boot anywhere but a single-process local instance, so there is
# no second worker to share a counter with. Only successful mints count;
# refused or invalid requests never consume budget.
MAX_SELF_PROVISION_MINTS_PER_CLIENT = 10
SELF_PROVISION_MINT_WINDOW_SECONDS = 3600.0

# Client address -> monotonic timestamps of successful mints inside the window.
_mint_timestamps: dict[str, list[float]] = {}
_mint_lock = asyncio.Lock()


def _self_provision_client_id(http_request: Request) -> str:
    """Return the non-spoofable peer address for mint budgeting.

    Forwarding headers are deliberately ignored: they are caller-controlled
    and would let one party rotate identities the way credential rotation
    defeats the global limiter.
    """
    if http_request.client is not None and http_request.client.host:
        return http_request.client.host
    return "unknown"


async def _check_self_provision_budget(client_id: str) -> float:
    """Reserve one mint for the client, or refuse with 429 when spent.

    Returns the reservation timestamp so a mint that later fails can hand
    its reservation back with ``_release_self_provision_budget``.
    """
    now = time.monotonic()
    window_start = now - SELF_PROVISION_MINT_WINDOW_SECONDS
    async with _mint_lock:
        recent = [ts for ts in _mint_timestamps.get(client_id, ()) if ts > window_start]
        if len(recent) >= MAX_SELF_PROVISION_MINTS_PER_CLIENT:
            retry_after = max(
                1, int(recent[0] + SELF_PROVISION_MINT_WINDOW_SECONDS - now) + 1
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "dev_key_self_provision_rate_limited",
                    "message": (
                        "Too many self-provisioned dev keys from this address. "
                        f"At most {MAX_SELF_PROVISION_MINTS_PER_CLIENT} mints "
                        "per hour per address on dev instances."
                    ),
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )
        recent.append(now)
        _mint_timestamps[client_id] = recent
        if len(_mint_timestamps) > 1024:
            for key, timestamps in list(_mint_timestamps.items()):
                if not timestamps or timestamps[-1] <= window_start:
                    del _mint_timestamps[key]
        return now


async def _release_self_provision_budget(client_id: str, reservation: float) -> None:
    """Hand back a reservation whose mint failed, so failures never consume it."""
    async with _mint_lock:
        timestamps = _mint_timestamps.get(client_id)
        if timestamps is not None:
            try:
                timestamps.remove(reservation)
            except ValueError:
                pass


def reset_dev_key_self_provision_limits_for_tests() -> None:
    """Clear per-address mint budgets. Tests only; never called by routes."""
    _mint_timestamps.clear()


class SelfProvisionRequest(BaseModel):
    """Everything is optional: a bare POST provisions a usable dev agent."""

    agent_id: str = Field(
        default="",
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]*$",
        description=("Identifier for the dev agent wallet. Generated when omitted."),
    )
    key_name: str = Field(default="self-provisioned-dev", max_length=64)
    budget_credits: float = Field(
        default=1000.0,
        ge=0,
        le=float(MAX_BUDGET_CREDITS),
        description="Synthetic dev credits granted to the agent wallet.",
    )


class SelfProvisionResponse(BaseModel):
    sponsor_wallet_id: str
    wallet_id: str
    agent_id: str
    key_id: str
    key_prefix: str
    api_key: str
    note: str


def _require_enabled() -> None:
    if not get_settings().ENABLE_DEV_KEY_SELF_PROVISION:
        raise HTTPException(status_code=404, detail="Not Found")


def _refuse_production_like() -> None:
    """Defense-in-depth: the boot guardrail already rejects this posture."""
    if is_production_like_environment(get_settings().ENVIRONMENT):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "dev_key_self_provision_forbidden",
                "message": (
                    "Self-serve dev key provisioning is local-only and is "
                    "never available in production-like environments."
                ),
            },
        )


def _reject_cross_origin(request: Request) -> None:
    """Reject cross-origin browser calls (DNS-rebinding hardening).

    This endpoint is unauthenticated and returns a live secret in its body,
    so under the default wildcard CORS an attacker page could ``fetch`` it
    against the developer's localhost and read the minted key cross-origin.
    A browser always sends ``Origin`` on such a request; non-browser dev
    agents send none and pass through. Mirrors
    ``app.routers.mcp_standard._validate_origin``.
    """
    origin = request.headers.get("origin")
    if not origin:
        return
    origin_host = urlsplit(origin).hostname
    allowed = {request.url.hostname}
    public_url = get_settings().PUBLIC_URL
    if public_url:
        allowed.add(urlsplit(public_url).hostname)
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


@router.post(
    "/self-provision",
    response_model=SelfProvisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Self-provision a wallet-scoped development API key (local only)",
    description=(
        "Mint a dev sponsor wallet, agent wallet, and wallet-scoped API key "
        "with no pre-shared secret. Requires ENABLE_DEV_KEY_SELF_PROVISION "
        "and a local-compatible ENVIRONMENT; production-like deployments "
        "refuse to boot with this enabled. The key is shown once."
    ),
)
async def self_provision_dev_key(
    request: SelfProvisionRequest,
    http_request: Request,
) -> SelfProvisionResponse:
    _require_enabled()
    _refuse_production_like()
    _reject_cross_origin(http_request)
    # Per-address mint budget, after the gates so refused requests never
    # consume it. Reserved up front so concurrent mints cannot all pass one
    # shared read; handed back if the mint below fails.
    client_id = _self_provision_client_id(http_request)
    reservation = await _check_self_provision_budget(client_id)

    agent_id = request.agent_id or f"dev-agent-{uuid4().hex[:8]}"
    budget = Decimal(str(request.budget_credits))

    try:
        money = get_agent_money()
        sponsor = await money.create_sponsor_wallet(
            sponsor_name=f"dev-self-provision:{agent_id}",
            email=f"{agent_id}@dev.local",
            initial_credits=budget,
            require_kyc=False,
        )
        agent = await money.create_agent_wallet(
            sponsor_wallet_id=sponsor.wallet_id,
            agent_id=agent_id,
            budget_credits=budget,
        )
        key = await get_api_key_service().create_key(
            wallet_id=agent.wallet_id,
            key_name=request.key_name,
        )
    except Exception:
        await _release_self_provision_budget(client_id, reservation)
        raise

    return SelfProvisionResponse(
        sponsor_wallet_id=sponsor.wallet_id,
        wallet_id=agent.wallet_id,
        agent_id=agent_id,
        key_id=key["key_id"],
        key_prefix=key["key_prefix"],
        api_key=key["api_key"],
        note=(
            "Store the api_key now; it is shown only once. The key is "
            "wallet-scoped (not bootstrap-admin) and its credits are "
            "synthetic dev credits."
        ),
    )
