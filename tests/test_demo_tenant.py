"""Self-serve demo tenant + per-key tool allowlists.

Covers the Product Hunt launch surface: anonymous issuance with abuse
controls, full-permission demo keys inside the demo tenant, tenant
containment (permits, money, routes, keys), revocation/rotation, the kill
switch, and the end-to-end permit → invoke → replay → receipt flow.

Conventions: each test takes ``clean_database`` (per-test wipe), the
module-local ``demo_settings`` fixture flips ``ENABLE_DEMO_TENANT`` on and
restores every ``DEMO_*`` value plus the in-memory issuance counters after
each test. Upstream tools are registered under unique names (except the
``partner.echo`` end-to-end) and unregistered in ``finally``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.trust_mode import TrustModeGuardrailError, validate_trust_mode_config
from app.db.database import get_session_factory
from app.db.models import APIKeyModel, WalletModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.agent_money import get_agent_money
from app.services.api_key_service import get_api_key_service
from app.services.demo_tenant import _alerted_buckets, _memory_counters
from app.services.service_registry import get_service_registry
from app.services.upstream_mcp import UpstreamMcpResult
from app.services.wallet_engine import CrossTenantTransferError
from tests.test_trust_helpers import BOOTSTRAP_HEADERS, provision_agent_wallet


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


_DEMO_SETTING_NAMES = (
    "ENABLE_DEMO_TENANT",
    "DEMO_ALLOWED_TOOLS",
    "DEMO_KEY_TTL_DAYS",
    "DEMO_KEY_MAX_USES",
    "DEMO_WALLET_CREDITS",
    "DEMO_WALLET_DAILY_LIMIT",
    "DEMO_MAX_PERMIT_CREDITS",
    "DEMO_MAX_PERMIT_TTL_MINUTES",
    "DEMO_ISSUE_PER_IP_PER_DAY",
    "DEMO_ISSUE_GLOBAL_PER_HOUR",
    "DEMO_ISSUE_GLOBAL_PER_DAY",
    "DEMO_MAX_LIVE_KEYS",
    "DEMO_ALERT_ISSUES_PER_HOUR",
    "DEMO_ALLOWED_ORIGINS",
)


@pytest.fixture
def demo_settings():
    """Enable the demo tenant with default (uncapped) limits for one test."""
    settings = get_settings()
    saved = {name: getattr(settings, name) for name in _DEMO_SETTING_NAMES}
    settings.ENABLE_DEMO_TENANT = True
    _memory_counters.clear()
    _alerted_buckets.clear()
    try:
        yield settings
    finally:
        for name, value in saved.items():
            setattr(settings, name, value)
        _memory_counters.clear()
        _alerted_buckets.clear()


async def issue_demo_key(client: AsyncClient) -> dict[str, Any]:
    """Mint a demo key through the public issuance endpoint."""
    resp = await client.post("/v1/demo/keys", json={})
    assert resp.status_code == 201, resp.text
    return resp.json()


def demo_headers(body: dict[str, Any]) -> dict[str, str]:
    return {"X-API-Key": body["api_key"]}


def _echo_result(arguments: dict[str, Any]) -> UpstreamMcpResult:
    payload = {
        "content": [{"type": "text", "text": "partner response"}],
        "structuredContent": {"echo": arguments},
        "isError": False,
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return UpstreamMcpResult(
        payload=payload,
        canonical_json=canonical,
        response_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        size_bytes=len(canonical.encode()),
        is_error=False,
    )


class _EchoExecutor:
    """Minimal successful upstream executor (mirrors partner.echo)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def call_tool(
        self,
        arguments: dict[str, Any],
        *,
        invocation_id: str,
        idempotency_key: str,
        before_dispatch,
    ) -> UpstreamMcpResult:
        self.calls.append(
            {
                "arguments": arguments,
                "invocation_id": invocation_id,
                "idempotency_key": idempotency_key,
            }
        )
        await before_dispatch()
        return _echo_result(arguments)


def register_echo_tool(tool_name: str) -> _EchoExecutor:
    executor = _EchoExecutor()
    get_service_registry().register_upstream(
        service_id=tool_name,
        name="Echo test tool",
        description="Controlled echo tool for demo-tenant tests",
        category=ServiceCategory.AGENT_COMMS,
        executor=executor,
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        credits_per_unit=2.0,
        upstream_tool_name=tool_name,
        upstream_origin="https://partner.example",
    )
    return executor


def unregister_tool(tool_name: str) -> None:
    get_service_registry().unregister_local(tool_name)


async def create_permit(
    client: AsyncClient,
    headers: dict[str, str],
    wallet_id: str,
    tool_name: str,
    *,
    issuer_wallet_id: str | None = None,
    subject_wallet_id: str | None = None,
    scopes: list[str] | None = None,
    max_credits: str = "5",
    minutes: int = 15,
    idem_key: str = "demo-permit-1",
) -> Any:
    return await client.post(
        "/v1/permits",
        json={
            "issuer_wallet_id": issuer_wallet_id or wallet_id,
            "subject_wallet_id": subject_wallet_id or wallet_id,
            "allowed_tools": [tool_name],
            "scopes": scopes or [f"tool:{tool_name}:invoke", "billing:charge"],
            "max_credits": max_credits,
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(minutes=minutes)
            ).isoformat(),
        },
        headers={**headers, "Idempotency-Key": idem_key},
    )


async def invoke_tool(
    client: AsyncClient,
    headers: dict[str, str],
    tool_name: str,
    wallet_id: str,
    permit_id: str,
    idempotency_key: str,
) -> Any:
    return await client.post(
        f"/mcp/tools/{tool_name}/invoke",
        json={
            "name": tool_name,
            "arguments": {"message": "hello"},
            "mcp_context": {
                "wallet_id": wallet_id,
                "permit_id": permit_id,
                "idempotency_key": idempotency_key,
            },
        },
        headers=headers,
    )


async def wallet_snapshot(wallet_id: str) -> tuple[Decimal, int]:
    """(balance, ledger entry count) for later unchanged-assertions."""
    from sqlalchemy import func

    from app.db.models import LedgerEntryModel

    factory = get_session_factory()
    async with factory() as session:
        wallet = await session.get(WalletModel, wallet_id)
        assert wallet is not None
        result = await session.execute(
            select(func.count())
            .select_from(LedgerEntryModel)
            .where(LedgerEntryModel.wallet_id == wallet_id)
        )
        return wallet.balance, int(result.scalar_one())


# --- Issuance defaults -----------------------------------------------------


@pytest.mark.anyio
async def test_issue_demo_key_defaults(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    body = await issue_demo_key(client)
    assert body["tenant"] == "demo"
    assert body["allowed_tools"] is None
    assert body["expires_at"] is None
    assert body["max_uses"] is None
    assert Decimal(str(body["budget_credits"])) == Decimal("1000")

    factory = get_session_factory()
    async with factory() as session:
        agent = await session.get(WalletModel, body["wallet_id"])
        sponsor = await session.get(WalletModel, body["sponsor_wallet_id"])
        assert agent is not None and agent.tenant == "demo"
        assert sponsor is not None and sponsor.tenant == "demo"
        assert agent.balance == Decimal("1000")
        key = (
            await session.execute(
                select(APIKeyModel).where(APIKeyModel.key_id == body["key_id"])
            )
        ).scalar_one()
        assert key.tenant == "demo"
        assert key.allowed_tools_json is None
        assert key.expires_at is None
        assert key.max_uses is None

    me = await client.get("/v1/me/authority", headers=demo_headers(body))
    assert me.status_code == 200, me.text


@pytest.mark.anyio
async def test_kill_switch_off_404_and_refuses_existing_key(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    body = await issue_demo_key(client)
    headers = demo_headers(body)

    get_settings().ENABLE_DEMO_TENANT = False
    try:
        resp = await client.post("/v1/demo/keys", json={})
        assert resp.status_code == 404
        me = await client.get("/v1/me/authority", headers=headers)
        assert me.status_code == 403
        assert me.json()["detail"]["error"] == "demo_tenant_disabled"
    finally:
        get_settings().ENABLE_DEMO_TENANT = True

    me = await client.get("/v1/me/authority", headers=headers)
    assert me.status_code == 200


@pytest.mark.anyio
async def test_origin_check(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    evil = await client.post(
        "/v1/demo/keys", json={}, headers={"Origin": "https://evil.example"}
    )
    assert evil.status_code == 403
    assert evil.json()["detail"]["error"] == "origin_not_allowed"


# --- Default full permissions ----------------------------------------------


@pytest.mark.anyio
async def test_default_demo_key_uses_any_tool_scope_and_budget(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    tool_a = "demo-tool-alpha"
    tool_b = "demo-tool-beta"
    register_echo_tool(tool_a)
    register_echo_tool(tool_b)
    try:
        body = await issue_demo_key(client)
        headers = demo_headers(body)
        wallet_id = body["wallet_id"]

        permit = await create_permit(
            client,
            headers,
            wallet_id,
            tool_a,
            scopes=[f"tool:{tool_a}:invoke", "billing:charge", "custom:bonus-scope"],
            max_credits="500",
            minutes=60 * 20,
            idem_key="demo-permit-any-1",
        )
        assert permit.status_code == 201, permit.text
        permit_id_a = permit.json()["permit_id"]

        permit_b = await create_permit(
            client, headers, wallet_id, tool_b, idem_key="demo-permit-any-2"
        )
        assert permit_b.status_code == 201, permit_b.text

        first = await invoke_tool(
            client, headers, tool_a, wallet_id, permit_id_a, "k-1"
        )
        assert first.status_code == 200, first.text
        second = await invoke_tool(
            client, headers, tool_b, wallet_id, permit_b.json()["permit_id"], "k-2"
        )
        assert second.status_code == 200, second.text
    finally:
        unregister_tool(tool_a)
        unregister_tool(tool_b)


@pytest.mark.anyio
async def test_default_demo_key_has_no_expiry_or_use_cap(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    body = await issue_demo_key(client)
    headers = demo_headers(body)
    for _ in range(5):
        me = await client.get("/v1/me/authority", headers=headers)
        assert me.status_code == 200


# --- Optional limits (one test each) ----------------------------------------


@pytest.mark.anyio
async def test_demo_allowed_tools_limit(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    demo_settings.DEMO_ALLOWED_TOOLS = "partner.echo"
    other = "demo-tool-outside"
    register_echo_tool("partner.echo")
    register_echo_tool(other)
    try:
        body = await issue_demo_key(client)
        assert body["allowed_tools"] == ["partner.echo"]
        headers = demo_headers(body)
        wallet_id = body["wallet_id"]
        before = await wallet_snapshot(wallet_id)

        permit = await create_permit(
            client, headers, wallet_id, other, idem_key="demo-cap-tool-1"
        )
        assert permit.status_code == 403
        assert permit.json()["detail"]["error"] == "key_tool_not_allowed"

        denied = await invoke_tool(client, headers, other, wallet_id, "nope", "k-x")
        assert denied.status_code == 403
        assert denied.json()["detail"]["error"] == "key_tool_not_allowed"
        assert await wallet_snapshot(wallet_id) == before
    finally:
        unregister_tool("partner.echo")
        unregister_tool(other)


@pytest.mark.anyio
async def test_demo_key_ttl_days_limit(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    demo_settings.DEMO_KEY_TTL_DAYS = 3
    body = await issue_demo_key(client)
    assert body["expires_at"] is not None
    expires = datetime.fromisoformat(body["expires_at"])
    if expires.tzinfo is not None:
        expires = expires.replace(tzinfo=None)
    delta = expires - datetime.now(timezone.utc).replace(tzinfo=None)
    assert timedelta(days=2) < delta <= timedelta(days=3, minutes=5)


@pytest.mark.anyio
async def test_demo_key_max_uses_limit(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    demo_settings.DEMO_KEY_MAX_USES = 3
    body = await issue_demo_key(client)
    assert body["max_uses"] == 3
    headers = demo_headers(body)
    for _ in range(3):
        me = await client.get("/v1/me/authority", headers=headers)
        assert me.status_code == 200
    fourth = await client.get("/v1/me/authority", headers=headers)
    assert fourth.status_code in (401, 403)


@pytest.mark.anyio
async def test_demo_max_permit_credits_limit(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    demo_settings.DEMO_MAX_PERMIT_CREDITS = Decimal("5")
    body = await issue_demo_key(client)
    headers = demo_headers(body)
    wallet_id = body["wallet_id"]

    too_big = await create_permit(
        client,
        headers,
        wallet_id,
        "partner.echo",
        max_credits="6",
        idem_key="demo-cap-credits-1",
    )
    assert too_big.status_code == 403
    assert too_big.json()["detail"]["error"] == "demo_permit_out_of_bounds"

    ok = await create_permit(
        client,
        headers,
        wallet_id,
        "partner.echo",
        max_credits="5",
        idem_key="demo-cap-credits-2",
    )
    assert ok.status_code == 201, ok.text


@pytest.mark.anyio
async def test_demo_max_permit_ttl_limit(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    demo_settings.DEMO_MAX_PERMIT_TTL_MINUTES = 30
    body = await issue_demo_key(client)
    headers = demo_headers(body)
    wallet_id = body["wallet_id"]

    too_far = await create_permit(
        client,
        headers,
        wallet_id,
        "partner.echo",
        minutes=60,
        idem_key="demo-cap-ttl-1",
    )
    assert too_far.status_code == 403
    assert too_far.json()["detail"]["error"] == "demo_permit_out_of_bounds"

    ok = await create_permit(
        client,
        headers,
        wallet_id,
        "partner.echo",
        minutes=15,
        idem_key="demo-cap-ttl-2",
    )
    assert ok.status_code == 201, ok.text


@pytest.mark.anyio
async def test_demo_wallet_daily_limit_limit(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    demo_settings.DEMO_WALLET_DAILY_LIMIT = Decimal("50")
    body = await issue_demo_key(client)
    factory = get_session_factory()
    async with factory() as session:
        wallet = await session.get(WalletModel, body["wallet_id"])
        assert wallet is not None
        assert wallet.daily_limit == Decimal("50")


# --- Generic allowlist on non-demo keys --------------------------------------


async def _bounded_normal_key(client: AsyncClient, wallet_id: str) -> dict[str, str]:
    """Mint a NON-demo key carrying allowed_tools via the key service."""
    key = await get_api_key_service().create_key(
        wallet_id=wallet_id,
        key_name="bounded",
        allowed_tools=["demo-tool-bounded-echo"],
    )
    return {"X-API-Key": key["api_key"]}


@pytest.mark.anyio
async def test_key_allowlist_permit_and_invoke_denials(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    tool_in = "demo-tool-bounded-echo"
    tool_out = "demo-tool-bounded-other"
    register_echo_tool(tool_in)
    register_echo_tool(tool_out)
    try:
        provisioned = await provision_agent_wallet(client)
        wallet_id = provisioned["agent_wallet_id"]
        bounded = await _bounded_normal_key(client, wallet_id)
        before = await wallet_snapshot(wallet_id)

        permit = await create_permit(
            client, bounded, wallet_id, tool_out, idem_key="demo-allow-1"
        )
        assert permit.status_code == 403
        assert permit.json()["detail"]["error"] == "key_tool_not_allowed"

        scoped = await create_permit(
            client,
            bounded,
            wallet_id,
            tool_in,
            scopes=[f"tool:{tool_out}:invoke", "billing:charge"],
            idem_key="demo-allow-2",
        )
        assert scoped.status_code == 403
        assert scoped.json()["detail"]["error"] == "key_tool_not_allowed"

        ok_permit = await create_permit(
            client, bounded, wallet_id, tool_in, idem_key="demo-allow-3"
        )
        assert ok_permit.status_code == 201, ok_permit.text

        denied = await invoke_tool(
            client, bounded, tool_out, wallet_id, "nope", "k-bounded-1"
        )
        assert denied.status_code == 403
        assert denied.json()["detail"]["error"] == "key_tool_not_allowed"
        assert await wallet_snapshot(wallet_id) == before

        allowed = await invoke_tool(
            client,
            bounded,
            tool_in,
            wallet_id,
            ok_permit.json()["permit_id"],
            "k-bounded-2",
        )
        assert allowed.status_code == 200, allowed.text
    finally:
        unregister_tool(tool_in)
        unregister_tool(tool_out)


@pytest.mark.anyio
async def test_unrestricted_key_unchanged(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    tool_name = "demo-tool-open-echo"
    register_echo_tool(tool_name)
    try:
        provisioned = await provision_agent_wallet(client)
        wallet_id = provisioned["agent_wallet_id"]
        permit = await create_permit(
            client,
            provisioned["agent_headers"],
            wallet_id,
            tool_name,
            idem_key="demo-allow-open-1",
        )
        assert permit.status_code == 201, permit.text
        invoked = await invoke_tool(
            client,
            provisioned["agent_headers"],
            tool_name,
            wallet_id,
            permit.json()["permit_id"],
            "k-open-1",
        )
        assert invoked.status_code == 200, invoked.text
    finally:
        unregister_tool(tool_name)


@pytest.mark.anyio
async def test_jwt_path_carries_allowlist(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    """A JWT derived from an allowlisted key enforces the same bounds."""
    tool_in = "demo-tool-jwt-echo"
    tool_out = "demo-tool-jwt-other"
    settings = get_settings()
    saved_signing_key = settings.TRUST_SIGNING_PRIVATE_KEY_B64
    settings.TRUST_SIGNING_PRIVATE_KEY_B64 = (
        "dGVzdC1zaWduaW5nLWtleS1tYXRlcmlhbC0zMmJ5dGU="
    )
    register_echo_tool(tool_in)
    register_echo_tool(tool_out)
    try:
        provisioned = await provision_agent_wallet(client)
        wallet_id = provisioned["agent_wallet_id"]
        key = await get_api_key_service().create_key(
            wallet_id=wallet_id,
            key_name="jwt-bounded",
            allowed_tools=[tool_in],
        )
        exchange = await client.post("/v1/auth/token", json={"api_key": key["api_key"]})
        assert exchange.status_code == 200, exchange.text
        bearer = {"Authorization": f"Bearer {exchange.json()['access_token']}"}

        denied = await invoke_tool(
            client, bearer, tool_out, wallet_id, "nope", "k-jwt-1"
        )
        assert denied.status_code == 403
        assert denied.json()["detail"]["error"] == "key_tool_not_allowed"
    finally:
        unregister_tool(tool_in)
        unregister_tool(tool_out)
        settings.TRUST_SIGNING_PRIVATE_KEY_B64 = saved_signing_key


# --- Issuance abuse controls --------------------------------------------------


@pytest.mark.anyio
async def test_per_ip_issuance_limit(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    demo_settings.DEMO_ISSUE_PER_IP_PER_DAY = 2
    assert (await client.post("/v1/demo/keys", json={})).status_code == 201
    assert (await client.post("/v1/demo/keys", json={})).status_code == 201
    third = await client.post("/v1/demo/keys", json={})
    assert third.status_code == 429
    assert third.json()["detail"]["error"] == "demo_issuance_rate_limited"
    assert third.json()["detail"]["scope"] == "ip"
    assert "Retry-After" in third.headers


@pytest.mark.anyio
async def test_global_hour_limit_alerts_exactly_once(
    client: AsyncClient,
    clean_database: None,
    demo_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import notifications as notifications_module

    calls: list[dict[str, Any]] = []

    async def fake_alert(self, wallet_id: str, alert_type: str, message: str) -> None:
        calls.append(
            {"wallet_id": wallet_id, "alert_type": alert_type, "message": message}
        )

    monkeypatch.setattr(
        notifications_module.NotificationService, "send_security_alert", fake_alert
    )
    demo_settings.DEMO_ISSUE_GLOBAL_PER_HOUR = 1
    assert (await client.post("/v1/demo/keys", json={})).status_code == 201
    second = await client.post("/v1/demo/keys", json={})
    assert second.status_code == 429
    assert second.json()["detail"]["scope"] == "global_hour"
    third = await client.post("/v1/demo/keys", json={})
    assert third.status_code == 429
    assert len(calls) == 1
    assert calls[0]["alert_type"] == "demo_issuance_global_hour"


@pytest.mark.anyio
async def test_live_key_cap(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    demo_settings.DEMO_MAX_LIVE_KEYS = 1
    assert (await client.post("/v1/demo/keys", json={})).status_code == 201
    capped = await client.post("/v1/demo/keys", json={})
    assert capped.status_code == 429
    assert capped.json()["detail"]["scope"] == "live_keys"


@pytest.mark.anyio
async def test_expired_demo_key_refused(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    demo_settings.DEMO_KEY_TTL_DAYS = 3
    body = await issue_demo_key(client)
    headers = demo_headers(body)
    factory = get_session_factory()
    async with factory() as session:
        key = (
            await session.execute(
                select(APIKeyModel).where(APIKeyModel.key_id == body["key_id"])
            )
        ).scalar_one()
        key.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            seconds=1
        )
        await session.commit()
    me = await client.get("/v1/me/authority", headers=headers)
    assert me.status_code in (401, 403)


# --- Revocation and rotation ---------------------------------------------------


@pytest.mark.anyio
async def test_self_revoke_and_admin_revoke_all(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    first = await issue_demo_key(client)
    second = await issue_demo_key(client)

    revoke = await client.post("/v1/demo/keys/revoke", headers=demo_headers(first))
    assert revoke.status_code == 200
    dead = await client.get("/v1/me/authority", headers=demo_headers(first))
    assert dead.status_code in (401, 403)
    live = await client.get("/v1/me/authority", headers=demo_headers(second))
    assert live.status_code == 200

    wipe = await client.post("/v1/demo/admin/revoke-all", headers=BOOTSTRAP_HEADERS)
    assert wipe.status_code == 200
    assert wipe.json()["revoked_count"] == 1
    gone = await client.get("/v1/me/authority", headers=demo_headers(second))
    assert gone.status_code in (401, 403)


@pytest.mark.anyio
async def test_admin_revoke_all_works_with_kill_switch_off(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    """Operators can permanently revoke demo keys while the tenant is off,
    so re-enabling the flag does not resurrect them."""
    body = await issue_demo_key(client)
    demo_settings.ENABLE_DEMO_TENANT = False
    wipe = await client.post("/v1/demo/admin/revoke-all", headers=BOOTSTRAP_HEADERS)
    assert wipe.status_code == 200
    assert wipe.json()["revoked_count"] == 1
    stats = await client.get("/v1/demo/admin/stats", headers=BOOTSTRAP_HEADERS)
    assert stats.status_code == 200
    assert stats.json()["live_demo_keys"] == 0
    demo_settings.ENABLE_DEMO_TENANT = True
    revived = await client.get("/v1/me/authority", headers=demo_headers(body))
    assert revived.status_code in (401, 403)
    # Still bootstrap-only with the flag off.
    denied = await client.post("/v1/demo/admin/revoke-all", headers=demo_headers(body))
    assert denied.status_code in (401, 403)


@pytest.mark.anyio
async def test_admin_single_revoke_demo_only(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    body = await issue_demo_key(client)
    provisioned = await provision_agent_wallet(client)

    single = await client.post(
        f"/v1/demo/admin/keys/{body['key_id']}/revoke", headers=BOOTSTRAP_HEADERS
    )
    assert single.status_code == 200
    dead = await client.get("/v1/me/authority", headers=demo_headers(body))
    assert dead.status_code in (401, 403)

    not_demo = await client.post(
        f"/v1/demo/admin/keys/{provisioned['key_id']}/revoke",
        headers=BOOTSTRAP_HEADERS,
    )
    assert not_demo.status_code == 404


@pytest.mark.anyio
async def test_demo_rotation_inherits_and_kills_old(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    demo_settings.DEMO_KEY_TTL_DAYS = 3
    demo_settings.DEMO_KEY_MAX_USES = 10
    demo_settings.DEMO_ALLOWED_TOOLS = "partner.echo"
    body = await issue_demo_key(client)
    old_key = body["api_key"]
    factory = get_session_factory()
    async with factory() as session:
        old_row = (
            await session.execute(
                select(APIKeyModel).where(APIKeyModel.key_id == body["key_id"])
            )
        ).scalar_one()
        old_max, old_uses = old_row.max_uses, old_row.use_count

    rotated = await client.post("/v1/demo/keys/rotate", headers=demo_headers(body))
    assert rotated.status_code == 200, rotated.text
    new_body = rotated.json()
    assert new_body["tenant"] == "demo"
    # Same instant (rotation never extends expiry); compare parsed with a
    # small tolerance for storage rounding, since the inherited naive-UTC
    # value serializes without the +00:00 suffix.
    old_expires = datetime.fromisoformat(body["expires_at"]).replace(tzinfo=None)
    new_expires = datetime.fromisoformat(new_body["expires_at"]).replace(tzinfo=None)
    assert new_expires <= old_expires
    assert abs((old_expires - new_expires).total_seconds()) < 60

    async with factory() as session:
        new_row = (
            await session.execute(
                select(APIKeyModel).where(APIKeyModel.key_id == new_body["key_id"])
            )
        ).scalar_one()
        assert new_row.tenant == "demo"
        assert new_row.allowed_tools_json == '["partner.echo"]'
        # Remaining uses carry over. The rotate call authenticates (consuming
        # one use) before rotate_key snapshots the remainder, so expect the
        # pre-rotation remainder minus that call.
        assert new_row.max_uses == max(old_max - old_uses - 1, 0)

    old_dead = await client.get("/v1/me/authority", headers={"X-API-Key": old_key})
    assert old_dead.status_code in (401, 403)
    new_live = await client.get("/v1/me/authority", headers=demo_headers(new_body))
    assert new_live.status_code == 200

    non_demo = await provision_agent_wallet(client)
    forbidden = await client.post(
        "/v1/demo/keys/rotate", headers=non_demo["agent_headers"]
    )
    assert forbidden.status_code == 403


@pytest.mark.anyio
async def test_demo_key_cannot_mint_sibling_via_api_keys(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    body = await issue_demo_key(client)
    headers = demo_headers(body)
    attempt = await client.post(
        "/v1/api-keys",
        json={"wallet_id": body["wallet_id"], "key_name": "sibling"},
        headers=headers,
    )
    assert attempt.status_code == 403
    assert attempt.json()["detail"]["error"] == "demo_key_route_forbidden"
    # Belt and braces: the tenant label alone marks the key bounded, so
    # even without the route denylist it could not mint a sibling.
    assert await get_api_key_service().is_key_bounded(body["key_id"]) is True


@pytest.mark.anyio
async def test_boot_guardrail_needs_redis_with_flag_on() -> None:
    import base64

    signing = base64.b64encode(b"0" * 32).decode()
    with pytest.raises(TrustModeGuardrailError) as exc_info:
        validate_trust_mode_config(
            environment="production",
            trust_mode_enabled=True,
            signing_private_key_b64=signing,
            allow_legacy_unpermitted_mcp=False,
            enable_proof_surfaces=False,
            enable_demo_tenant=True,
            redis_url="",
            public_url="https://api.example.com",
            database_url="postgresql+asyncpg://db.example/app",
        )
    assert "REDIS_URL" in str(exc_info.value)
    validate_trust_mode_config(
        environment="production",
        trust_mode_enabled=True,
        signing_private_key_b64=signing,
        allow_legacy_unpermitted_mcp=False,
        enable_proof_surfaces=False,
        enable_demo_tenant=True,
        redis_url="redis://redis.internal:6379/0",
        public_url="https://api.example.com",
        database_url="postgresql+asyncpg://db.example/app",
    )


# --- Cross-tenant isolation --------------------------------------------------


@pytest.mark.anyio
async def test_demo_key_cannot_touch_real_wallet_or_ledger(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    """Every demo→real touchpoint is refused; the real wallet is untouched."""
    tool_name = "demo-tool-xecho"
    register_echo_tool(tool_name)
    try:
        real = await provision_agent_wallet(client)
        real_wallet = real["agent_wallet_id"]
        demo = await issue_demo_key(client)
        demo_headers_map = demo_headers(demo)
        demo_wallet = demo["wallet_id"]
        real_before = await wallet_snapshot(real_wallet)

        # Reads of a real wallet / ledger.
        assert (
            await client.get(
                f"/v1/billing/wallets/{real_wallet}", headers=demo_headers_map
            )
        ).status_code == 403
        assert (
            await client.get(
                f"/v1/billing/ledger/{real_wallet}", headers=demo_headers_map
            )
        ).status_code == 403

        # Charge against a real wallet.
        charge = await client.post(
            "/v1/billing/charge",
            params={"wallet_id": real_wallet, "units": 1},
            headers=demo_headers_map,
        )
        assert charge.status_code == 403

        # Permit naming a real wallet as issuer (ownership) or subject.
        issuer_real = await create_permit(
            client,
            demo_headers_map,
            demo_wallet,
            tool_name,
            issuer_wallet_id=real_wallet,
            subject_wallet_id=real_wallet,
            idem_key="demo-x-issuer",
        )
        assert issuer_real.status_code == 403
        subject_real = await create_permit(
            client,
            demo_headers_map,
            demo_wallet,
            tool_name,
            subject_wallet_id=real_wallet,
            idem_key="demo-x-subject",
        )
        assert subject_real.status_code == 403
        assert subject_real.json()["detail"]["error"] == "demo_permit_out_of_bounds"

        # Invoke charging a real wallet.
        permit = await create_permit(
            client, demo_headers_map, demo_wallet, tool_name, idem_key="demo-x-ok"
        )
        assert permit.status_code == 201, permit.text
        invoked = await invoke_tool(
            client,
            demo_headers_map,
            tool_name,
            real_wallet,
            permit.json()["permit_id"],
            "k-x-1",
        )
        assert invoked.status_code == 403

        # Minting a key for a real wallet.
        mint = await client.post(
            "/v1/api-keys",
            json={"wallet_id": real_wallet, "key_name": "x"},
            headers=demo_headers_map,
        )
        assert mint.status_code == 403

        # Cross-tenant transfer at the service layer, both directions.
        money = get_agent_money()
        with pytest.raises(CrossTenantTransferError):
            await money.transfer(
                demo_wallet, real_wallet, Decimal("1"), description="x-demo-real"
            )
        with pytest.raises(CrossTenantTransferError):
            await money.transfer(
                real_wallet, demo_wallet, Decimal("1"), description="x-real-demo"
            )

        # Same-tenant demo→demo transfer still works.
        demo2 = await issue_demo_key(client)
        same = await money.transfer(
            demo_wallet, demo2["wallet_id"], Decimal("1"), description="x-demo-demo"
        )
        assert same["status"] == "completed" or "transfer_id" in same

        assert await wallet_snapshot(real_wallet) == real_before
    finally:
        unregister_tool(tool_name)


@pytest.mark.anyio
async def test_transfer_route_refuses_cross_tenant(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    real = await provision_agent_wallet(client)
    demo = await issue_demo_key(client)
    resp = await client.post(
        "/v1/billing/transfer",
        params={
            "from_wallet_id": demo["wallet_id"],
            "to_wallet_id": real["agent_wallet_id"],
            "amount": 1,
        },
        headers=demo_headers(demo),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "cross_tenant_transfer_refused"


@pytest.mark.anyio
async def test_normal_key_cannot_touch_demo_wallet(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    tool_name = "demo-tool-yecho"
    register_echo_tool(tool_name)
    try:
        real = await provision_agent_wallet(client)
        demo = await issue_demo_key(client)
        demo_wallet = demo["wallet_id"]

        permit = await create_permit(
            client,
            real["agent_headers"],
            real["agent_wallet_id"],
            tool_name,
            issuer_wallet_id=real["agent_wallet_id"],
            subject_wallet_id=demo_wallet,
            idem_key="demo-y-cross",
        )
        assert permit.status_code == 403

        invoked = await invoke_tool(
            client,
            real["agent_headers"],
            tool_name,
            demo_wallet,
            "nope",
            "k-y-1",
        )
        assert invoked.status_code == 403
    finally:
        unregister_tool(tool_name)


# --- Tenant inheritance -------------------------------------------------------


@pytest.mark.anyio
async def test_key_minted_for_demo_wallet_via_api_keys_is_demo_and_dies(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    """The generic key route stamps tenant from the wallet (bootstrap mint).

    A demo key itself can never reach this route (bounded + denylisted), so
    the inheritance is exercised the way it happens in production: a
    bootstrap admin mints for a demo wallet, and the key is demo-bounded
    from birth.
    """
    demo = await issue_demo_key(client)
    created = await client.post(
        "/v1/api-keys",
        json={"wallet_id": demo["wallet_id"], "key_name": "admin-minted-demo"},
        headers=BOOTSTRAP_HEADERS,
    )
    assert created.status_code == 201, created.text
    key_id = created.json()["key_id"]

    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(APIKeyModel, key_id)
        assert row is not None and row.tenant == "demo"

    headers = {"X-API-Key": created.json()["api_key"]}
    assert (await client.get("/v1/me/authority", headers=headers)).status_code == 200
    get_settings().ENABLE_DEMO_TENANT = False
    try:
        refused = await client.get("/v1/me/authority", headers=headers)
        assert refused.status_code == 403
        assert refused.json()["detail"]["error"] == "demo_tenant_disabled"
    finally:
        get_settings().ENABLE_DEMO_TENANT = True


@pytest.mark.anyio
async def test_child_wallet_of_demo_is_demo_and_dies(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    demo = await issue_demo_key(client)
    money = get_agent_money()
    child = await money.create_child_wallet(
        parent_wallet_id=demo["wallet_id"],
        child_agent_id="demo-grandchild",
        budget_credits=Decimal("10"),
        max_spend=Decimal("10"),
    )
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(WalletModel, child.wallet_id)
        assert row is not None and row.tenant == "demo"

    key = await get_api_key_service().create_key(wallet_id=child.wallet_id)
    assert key["tenant"] == "demo"
    headers = {"X-API-Key": key["api_key"]}
    assert (await client.get("/v1/me/authority", headers=headers)).status_code == 200
    get_settings().ENABLE_DEMO_TENANT = False
    try:
        refused = await client.get("/v1/me/authority", headers=headers)
        assert refused.status_code == 403
        assert refused.json()["detail"]["error"] == "demo_tenant_disabled"
    finally:
        get_settings().ENABLE_DEMO_TENANT = True


@pytest.mark.anyio
async def test_wallet_tenant_without_key_label_still_demo(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    """Fail closed: a live key on a demo wallet is demo even if unlabeled."""
    demo = await issue_demo_key(client)
    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                select(APIKeyModel).where(APIKeyModel.key_id == demo["key_id"])
            )
        ).scalar_one()
        row.tenant = None
        await session.commit()

    get_settings().ENABLE_DEMO_TENANT = False
    try:
        refused = await client.get("/v1/me/authority", headers=demo_headers(demo))
        assert refused.status_code == 403
        assert refused.json()["detail"]["error"] == "demo_tenant_disabled"
    finally:
        get_settings().ENABLE_DEMO_TENANT = True


# --- Route denylist ------------------------------------------------------------


@pytest.mark.anyio
async def test_demo_route_denylist(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    demo = await issue_demo_key(client)
    headers = demo_headers(demo)
    wallet_id = demo["wallet_id"]

    for method, path in (
        ("POST", "/v1/api-keys"),
        ("GET", "/v1/signing-keys/active"),
        ("POST", "/v1/billing/top-up"),
        ("POST", "/v1/billing/acp/checkout"),
        ("POST", "/v1/kyc/sessions"),
        ("POST", "/v1/x402/settle"),
        ("POST", "/v1/pods"),
        ("POST", "/v1/billing/wallets/child"),
    ):
        resp = await client.request(method, path, headers=headers, json={})
        assert resp.status_code == 403, (method, path, resp.status_code)
        assert resp.json()["detail"]["error"] == "demo_key_route_forbidden", (
            method,
            path,
        )

    # Reachable: own reads, own charge, permit list, receipt flow surfaces.
    assert (await client.get("/v1/me/authority", headers=headers)).status_code == 200
    assert (
        await client.get(f"/v1/billing/wallets/{wallet_id}", headers=headers)
    ).status_code == 200
    assert (
        await client.get(f"/v1/billing/ledger/{wallet_id}", headers=headers)
    ).status_code == 200
    assert (await client.get("/v1/permits", headers=headers)).status_code == 200


# --- End-to-end happy path ------------------------------------------------------


@pytest.mark.anyio
async def test_demo_end_to_end_permit_invoke_replay_receipt(
    client: AsyncClient, clean_database: None, demo_settings
) -> None:
    register_echo_tool("partner.echo")
    try:
        body = await issue_demo_key(client)
        headers = demo_headers(body)
        wallet_id = body["wallet_id"]

        permit = await create_permit(
            client,
            headers,
            wallet_id,
            "partner.echo",
            max_credits="5",
            minutes=15,
            idem_key="demo-e2e-permit",
        )
        assert permit.status_code == 201, permit.text
        permit_id = permit.json()["permit_id"]

        first = await invoke_tool(
            client, headers, "partner.echo", wallet_id, permit_id, "demo-e2e-run-1"
        )
        assert first.status_code == 200, first.text
        receipt_id = first.json()["receipt"]["receipt_id"]

        replay = await invoke_tool(
            client, headers, "partner.echo", wallet_id, permit_id, "demo-e2e-run-1"
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["receipt"]["receipt_id"] == receipt_id

        portable = await client.get(
            f"/v1/receipts/{receipt_id}/portable", headers=headers
        )
        assert portable.status_code == 200, portable.text

        trust_keys = await client.get("/.well-known/trust-keys.json")
        assert trust_keys.status_code == 200
    finally:
        unregister_tool("partner.echo")


# --- Model / migration parity ----------------------------------------------------


def test_demo_columns_exist_on_models() -> None:
    assert "allowed_tools_json" in APIKeyModel.model_fields
    assert "tenant" in APIKeyModel.model_fields
    assert "tenant" in WalletModel.model_fields
