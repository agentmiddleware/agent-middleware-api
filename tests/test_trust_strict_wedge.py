"""Strict trust-mode run of the core wedge loop.

The default suite runs in permissive trust mode (see tests/conftest.py), so
a bug that only appears with production trust flags passes everything except
the few tests that flip strict mode back on. tests/test_mcp_trust_mode.py
covers strict denials; this module covers the successful path in strict mode:
permit, invoke, meter, receipt, audit. If a strict-only regression breaks
permitted invokes, receipt issuance, or debit accounting, these tests go red
while the permissive suite stays green.
"""

from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routers import mcp as mcp_router
from app.schemas.billing import ServiceCategory
from app.services.audit_log import list_audit_events
from app.services.service_registry import get_service_registry
from app.services.signing_keys import get_signing_key_service
from tests.test_trust_helpers import (
    create_tool_permit,
    provision_agent_wallet,
)


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
    signing_keys = get_signing_key_service()
    signing_keys._private_key = None


def _register_echo_tool(tool_name: str) -> None:
    registry = get_service_registry()

    def strict_wedge_echo(message: str = "ok") -> dict:
        return {"message": message}

    registry.register_local(
        service_id=tool_name,
        name=f"{tool_name} Echo",
        description="Strict wedge loop test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=strict_wedge_echo,
        credits_per_unit=2.0,
        unit_name="call",
    )


def _invoke_body(*, tool_name, wallet_id, request_id, permit_id=None, idem_key=None):
    mcp_context = {"wallet_id": wallet_id}
    if permit_id is not None:
        mcp_context["permit_id"] = permit_id
    if idem_key is not None:
        mcp_context["idempotency_key"] = idem_key
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


async def _tool_debit_count(*, client, wallet_id, headers, tool_name) -> int:
    ledger_resp = await client.get(
        f"/v1/billing/ledger/{wallet_id}",
        headers=headers,
    )
    assert ledger_resp.status_code == 200
    return len(
        [
            entry
            for entry in ledger_resp.json()["entries"]
            if entry["service_category"] == "agent_comms"
            and entry["action"] == "debit"
            and tool_name in entry["description"]
        ]
    )


@pytest.mark.anyio
async def test_strict_mode_permitted_invoke_completes_wedge_loop(
    client,
    clean_database,
    strict_trust_mode,
):
    """Permit, invoke, meter, receipt, audit all work with strict flags on."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    tool_name = "strict-wedge-loop-tool"
    registry = get_service_registry()
    _register_echo_tool(tool_name)
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=wallet_id,
            key_id=provisioned["key_id"],
            tool_name=tool_name,
            idem_key="strict-wedge-permit-1",
        )
        resp = await client.post(
            "/mcp/messages",
            json=_invoke_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                request_id="strict-wedge-call",
                permit_id=permit["permit_id"],
                idem_key="strict-wedge-idem-1",
            ),
            headers=provisioned["agent_headers"],
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert "error" not in payload, payload
        assert payload["result"]["isError"] is False
        receipt = payload["result"]["receipt"]
        assert receipt["receipt_id"]
        assert receipt["outcome"] == "success"
        assert (
            await _tool_debit_count(
                client=client,
                wallet_id=wallet_id,
                headers=provisioned["agent_headers"],
                tool_name=tool_name,
            )
            == 1
        )
        events = await list_audit_events(
            event="mcp.invoke",
            wallet_id=wallet_id,
            tool=tool_name,
            ok=True,
            limit=5,
        )
        assert events
        assert events[0].error is None
    finally:
        registry.unregister_local(tool_name)


@pytest.mark.anyio
async def test_strict_mode_denied_invoke_issues_no_receipt_or_debit(
    client,
    clean_database,
    strict_trust_mode,
):
    """A permit_required denial in strict mode leaves no receipt and no debit."""
    provisioned = await provision_agent_wallet(client)
    wallet_id = provisioned["agent_wallet_id"]
    tool_name = "strict-wedge-denied-tool"
    registry = get_service_registry()
    _register_echo_tool(tool_name)
    try:
        resp = await client.post(
            "/mcp/messages",
            json=_invoke_body(
                tool_name=tool_name,
                wallet_id=wallet_id,
                request_id="strict-wedge-denied-call",
            ),
            headers=provisioned["agent_headers"],
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["error"]["message"] == "permit_required"
        assert "receipt" not in payload.get("result", {})
        assert (
            await _tool_debit_count(
                client=client,
                wallet_id=wallet_id,
                headers=provisioned["agent_headers"],
                tool_name=tool_name,
            )
            == 0
        )
    finally:
        registry.unregister_local(tool_name)
