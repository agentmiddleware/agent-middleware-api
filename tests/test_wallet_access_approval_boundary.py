"""Pin the wallet-access helper as layer A only, and pin its callers.

``evaluate_wallet_access_for_tool`` (formerly ``evaluate_tool_invocation``)
checks wallet ownership and nothing else. A passing wallet check must never
be read as approval to run a tool: the governed MCP pipeline enforces the
permit gate (layer B) and the wallet-policy gate (layer C) separately after
it. These tests pin both halves:

- the helper itself stays wallet-only (it cannot see permits or policies);
- no live caller in ``app/routers/mcp.py`` treats it as full approval;
- the pipeline still denies a wallet-passing caller that lacks a permit or
  violates wallet policy.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from httpx import ASGITransport, AsyncClient

from app.core.auth import AuthContext
from app.main import app
from app.policy import decisions as decisions_module
from app.policy.decisions import evaluate_wallet_access_for_tool
from app.routers import mcp as mcp_router
from app.schemas.billing import ServiceCategory
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def strict_trust_mode(monkeypatch):
    raw_private_key = Ed25519PrivateKey.generate().private_bytes(
        Encoding.Raw,
        PrivateFormat.Raw,
        NoEncryption(),
    )
    monkeypatch.setattr(mcp_router.settings, "TRUST_MODE_ENABLED", True)
    monkeypatch.setattr(mcp_router.settings, "ALLOW_LEGACY_UNPERMITTED_MCP", False)
    monkeypatch.setattr(
        mcp_router.settings,
        "TRUST_SIGNING_PRIVATE_KEY_B64",
        base64.b64encode(raw_private_key).decode(),
    )


def _register_tool(tool_name: str) -> None:
    registry = get_service_registry()

    def echo_tool(message: str = "ok") -> dict:
        return {"message": message}

    registry.register_local(
        service_id=tool_name,
        name=f"{tool_name} Echo",
        description="Wallet-access boundary test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=echo_tool,
        credits_per_unit=2.0,
        unit_name="call",
    )


def _invoke_body(
    *,
    tool_name: str,
    wallet_id: str,
    request_id: str,
    permit_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    mcp_context: dict[str, str] = {"wallet_id": wallet_id}
    if permit_id is not None:
        mcp_context["permit_id"] = permit_id
    if idempotency_key is not None:
        mcp_context["idempotency_key"] = idempotency_key
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {"message": "hello"},
            "mcpContext": mcp_context,
        },
    }


def test_helper_allows_owner_without_any_permit_or_policy_input():
    """The helper signature cannot see permits or policies, so allow means
    wallet ownership only, never approval to execute."""
    auth = AuthContext(
        source="db",
        raw_key="runtime-key",
        key_id="key-1",
        wallet_id="wallet-1",
    )
    decision = evaluate_wallet_access_for_tool(
        auth=auth,
        wallet_id="wallet-1",
        tool_name="some-tool",
        estimated_cost=1.0,
        request_id="req-boundary-1",
    )
    assert decision.allowed is True
    assert decision.reason == "allowed"


@pytest.mark.anyio
async def test_helper_allows_owner_even_when_policy_denies_tool(client, clean_database):
    """A wallet-policy bundle that bans the tool does not move the wallet
    check: policy enforcement lives in the caller, not the helper."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    bundle = await client.post(
        "/v1/policies",
        json={
            "wallet_id": wallet_id,
            "name": "Only another tool",
            "allowed_tools": ["some-other-tool"],
        },
        headers={"X-API-Key": "test-key"},
    )
    assert bundle.status_code == 201

    auth = AuthContext(
        source="db",
        raw_key="runtime-key",
        key_id=provisioned["key_id"],
        wallet_id=wallet_id,
    )
    decision = evaluate_wallet_access_for_tool(
        auth=auth,
        wallet_id=wallet_id,
        tool_name="policy-blocked-tool",
        estimated_cost=2.0,
        request_id="req-boundary-2",
    )
    assert decision.allowed is True


def test_no_live_caller_uses_the_old_full_approval_name():
    """The misleading ``evaluate_tool_invocation`` name must not gate any
    live call path; only the backward-compatible alias may reference it."""
    source = Path(decisions_module.__file__).parent.parent / "routers" / "mcp.py"
    text = source.read_text()
    assert "evaluate_wallet_access_for_tool" in text
    assert "evaluate_tool_invocation" not in text


def test_governed_pipeline_still_enforces_permit_and_policy_after_wallet_check():
    """The wallet gate's caller composes the full approval: permit
    validation and wallet-policy evaluation must both run after the wallet
    check inside ``_execute_registered_tool_inner``."""
    source = (
        Path(decisions_module.__file__).parent.parent / "routers" / "mcp.py"
    ).read_text()
    inner = source.split("async def _execute_registered_tool_inner", 1)[1]
    wallet_gate = inner.index("evaluate_wallet_access_for_tool")
    after_gate = inner[wallet_gate:]
    assert "validate_for_action" in after_gate
    assert "evaluate_wallet_policy" in after_gate


@pytest.mark.anyio
async def test_wallet_pass_without_permit_is_still_denied(
    client, clean_database, strict_trust_mode
):
    """The wallet check passes for the owning key, yet the governed call is
    denied ``permit_required``: passing layer A is not approval."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    tool_name = "wallet-pass-no-permit-tool"
    _register_tool(tool_name)
    try:
        resp = await client.post(
            "/mcp/messages",
            json=_invoke_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                request_id="wallet-pass-no-permit-1",
            ),
            headers=provisioned["agent_headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["error"]["message"] == "permit_required"
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_wallet_pass_with_permit_still_denied_by_policy(
    client, clean_database, strict_trust_mode
):
    """Wallet check passes and the permit is valid for the tool, yet the
    call is denied ``tool_not_allowed`` by the wallet-policy bundle."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    tool_name = "wallet-pass-policy-denied-tool"
    _register_tool(tool_name)
    try:
        bundle = await client.post(
            "/v1/policies",
            json={
                "wallet_id": wallet_id,
                "name": "Only another tool",
                "allowed_tools": ["some-other-tool"],
            },
            headers={"X-API-Key": "test-key"},
        )
        assert bundle.status_code == 201
        permit = await create_tool_permit(
            client,
            wallet_id=wallet_id,
            key_id=provisioned["key_id"],
            tool_name=tool_name,
            idem_key="wallet-boundary-permit-1",
        )
        resp = await client.post(
            "/mcp/messages",
            json=_invoke_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                request_id="wallet-pass-policy-denied-1",
                permit_id=permit["permit_id"],
                idempotency_key="wallet-boundary-key-1",
            ),
            headers=provisioned["agent_headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["error"]["message"] == "tool_not_allowed"
    finally:
        get_service_registry().unregister_local(tool_name)


@pytest.mark.anyio
async def test_wallet_pass_with_wrong_tool_permit_is_still_denied(
    client, clean_database, strict_trust_mode
):
    """Wallet check passes but the permit does not cover the tool, so the
    call is denied ``permit_tool_not_allowed`` before policy or dispatch."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    tool_name = "wallet-pass-permit-denied-tool"
    _register_tool(tool_name)
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=wallet_id,
            key_id=provisioned["key_id"],
            tool_name="some-other-tool",
            idem_key="wallet-boundary-permit-2",
        )
        resp = await client.post(
            "/mcp/messages",
            json=_invoke_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                request_id="wallet-pass-permit-denied-1",
                permit_id=permit["permit_id"],
                idempotency_key="wallet-boundary-key-2",
            ),
            headers=provisioned["agent_headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["error"]["message"] == "permit_tool_not_allowed"
    finally:
        get_service_registry().unregister_local(tool_name)
