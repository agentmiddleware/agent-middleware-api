"""Human approval gate (Sentinel) on the governed invoke path.

Covers the full contract:

- Simulated approvals auto-approve in local/dev, marked simulated, and are
  refused in production-like environments (fail closed at permit creation AND
  at the invoke gate).
- Real mode drives Sentinel: pending returns a retryable -32005 without
  consuming the idempotency key or charging; approval lets the SAME key
  proceed to a charged, receipted invoke; rejection and local expiry produce
  terminal denied receipts that replay.
- approval_id is carried on the signed receipt (conditionally signed, so
  tampering fails verification) and in the signed audit metadata.
- Permit signatures cover requires_human_approval only when set, so flipping
  the stored flag in either direction invalidates the permit.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

import app.services.human_approval as human_approval_module
from app.core.config import get_settings
from app.db.database import get_session_factory
from app.db.models import HumanApprovalModel, PermitModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.human_approval import (
    HumanApprovalError,
    HumanApprovalService,
    HumanApprovalUnavailableError,
)
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import (
    BOOTSTRAP_HEADERS,
    create_tool_permit,
    provision_agent_wallet,
)

TOOL = "approval-echo"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def registered_tool():
    registry = get_service_registry()

    def approval_echo(message: str = "ok") -> dict:
        return {"message": message}

    registry.register_local(
        service_id=TOOL,
        name="Approval Echo",
        description="Governed human-approval test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=approval_echo,
        credits_per_unit=2.0,
        unit_name="call",
    )
    yield
    registry.unregister_local(TOOL)


@pytest.fixture
def fresh_service(monkeypatch):
    """Give each test an isolated HumanApprovalService instance."""
    service = HumanApprovalService()
    monkeypatch.setattr(human_approval_module, "_service", service)
    return service


def _sentinel_env(monkeypatch, *, simulated: bool, configured: bool = True):
    settings = get_settings()
    monkeypatch.setattr(settings, "SIMULATION_MODE_HUMAN_APPROVAL", simulated)
    monkeypatch.setattr(
        settings, "SENTINEL_API_URL", "https://sentinel.test" if configured else ""
    )
    monkeypatch.setattr(
        settings, "SENTINEL_API_KEY", "sk_test_" + "0" * 64 if configured else ""
    )
    monkeypatch.setattr(settings, "SENTINEL_WAIT_SECONDS", 0.0)
    return settings


class FakeSentinel:
    """Stands in for SentinelClient; decisions are scripted per test."""

    def __init__(self, status: str = "pending") -> None:
        self.status = status
        self.created: list[dict] = []
        self.polls = 0
        self.fail_with: Exception | None = None

    async def create_approval(self, **kwargs):
        if self.fail_with is not None:
            raise self.fail_with
        self.created.append(kwargs)
        return {"action_id": f"act_{uuid.uuid4().hex[:16]}", "status": "pending"}

    async def get_approval(self, action_id: str):
        if self.fail_with is not None:
            raise self.fail_with
        self.polls += 1
        payload = {"action_id": action_id, "status": self.status}
        if self.status in {"approved", "rejected"}:
            payload["decided_by"] = "reviewer@example.com"
            payload["reason"] = f"scripted {self.status}"
        return payload

    async def wait_approval(self, action_id: str, timeout: float):
        return await self.get_approval(action_id)


def _invoke_body(provisioned, permit, idem_key: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": f"call-{idem_key}",
        "method": "tools/call",
        "params": {
            "name": TOOL,
            "arguments": {"message": "hello"},
            "mcpContext": {
                "wallet_id": provisioned["agent_wallet_id"],
                "permit_id": permit["permit_id"],
                "idempotency_key": idem_key,
            },
        },
    }


async def _approval_permit(client, provisioned, *, idem_key: str) -> dict:
    resp = await client.post(
        "/v1/permits",
        json={
            "issuer_wallet_id": provisioned["agent_wallet_id"],
            "subject_wallet_id": provisioned["agent_wallet_id"],
            "subject_key_id": provisioned["key_id"],
            "allowed_tools": [TOOL],
            "scopes": [f"tool:{TOOL}:invoke", "billing:charge"],
            "max_credits": 50,
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(minutes=30)
            ).isoformat(),
            "requires_human_approval": True,
        },
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": idem_key},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _ledger_debits(client, wallet_id: str) -> int:
    resp = await client.get(f"/v1/billing/ledger/{wallet_id}", headers=BOOTSTRAP_HEADERS)
    assert resp.status_code == 200
    return sum(1 for entry in resp.json()["entries"] if entry["action"] == "debit")


# ---------------------------------------------------------------------------
# Simulation mode
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_simulated_approval_auto_approves_and_is_marked(
    client, clean_database, registered_tool, fresh_service, monkeypatch
):
    _sentinel_env(monkeypatch, simulated=True, configured=False)

    provisioned = await provision_agent_wallet(client)
    permit = await _approval_permit(client, provisioned, idem_key="sim-permit-1")
    assert permit["requires_human_approval"] is True

    resp = await client.post(
        "/mcp/messages",
        json=_invoke_body(provisioned, permit, "sim-invoke-1"),
        headers=provisioned["agent_headers"],
    )
    assert resp.status_code == 200
    payload = resp.json()
    receipt = payload["result"]["receipt"]
    assert receipt["outcome"] == "success"
    assert receipt["approval_id"], "success receipt must carry the approval id"

    # The stored approval row is explicitly marked simulated.
    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                select(HumanApprovalModel).where(
                    HumanApprovalModel.approval_id == receipt["approval_id"]
                )
            )
        ).scalar_one()
        assert row.simulated is True
        assert row.status == "approved"
        assert row.decided_by == "simulation"

    # Audit metadata records the approval and its simulated nature.
    events = await client.get(
        "/v1/audit/events",
        params={"wallet_id": provisioned["agent_wallet_id"], "event": "mcp.invoke"},
        headers=BOOTSTRAP_HEADERS,
    )
    assert events.status_code == 200
    matching = [
        e
        for e in events.json()["events"]
        if e["metadata"].get("approval_id") == receipt["approval_id"]
    ]
    assert matching, "audit event must link the approval"
    assert matching[0]["metadata"]["approval_simulated"] is True


@pytest.mark.anyio
async def test_simulated_mode_fails_closed_in_production_like_env(
    client, clean_database, registered_tool, fresh_service, monkeypatch
):
    settings = _sentinel_env(monkeypatch, simulated=True, configured=False)

    provisioned = await provision_agent_wallet(client)

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    resp = await client.post(
        "/v1/permits",
        json={
            "issuer_wallet_id": provisioned["agent_wallet_id"],
            "subject_wallet_id": provisioned["agent_wallet_id"],
            "subject_key_id": provisioned["key_id"],
            "allowed_tools": [TOOL],
            "scopes": [f"tool:{TOOL}:invoke", "billing:charge"],
            "max_credits": 50,
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(minutes=30)
            ).isoformat(),
            "requires_human_approval": True,
        },
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "prod-permit-1"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "human_approval_not_configured"

    # Even a permit minted before the environment became production-like is
    # not honored: the invoke-time gate re-checks and denies.
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    permit = await _approval_permit(client, provisioned, idem_key="prod-permit-2")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    invoke = await client.post(
        "/mcp/messages",
        json=_invoke_body(provisioned, permit, "prod-invoke-1"),
        headers=provisioned["agent_headers"],
    )
    assert invoke.status_code == 200
    error = invoke.json()["error"]
    assert error["code"] == -32003
    assert error["message"] == "human_approval_not_configured"
    assert error["data"]["receipt"]["outcome"] == "denied"


@pytest.mark.anyio
async def test_real_mode_without_config_rejects_permit_creation(
    client, clean_database, fresh_service, monkeypatch
):
    _sentinel_env(monkeypatch, simulated=False, configured=False)

    provisioned = await provision_agent_wallet(client)
    resp = await client.post(
        "/v1/permits",
        json={
            "issuer_wallet_id": provisioned["agent_wallet_id"],
            "subject_wallet_id": provisioned["agent_wallet_id"],
            "subject_key_id": provisioned["key_id"],
            "allowed_tools": [TOOL],
            "scopes": [f"tool:{TOOL}:invoke", "billing:charge"],
            "max_credits": 50,
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(minutes=30)
            ).isoformat(),
            "requires_human_approval": True,
        },
        headers={**BOOTSTRAP_HEADERS, "Idempotency-Key": "unconfigured-permit"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "human_approval_not_configured"


@pytest.mark.anyio
async def test_plain_permits_are_unaffected(
    client, clean_database, registered_tool, fresh_service, monkeypatch
):
    """A permit without the flag never touches the approval service."""
    _sentinel_env(monkeypatch, simulated=False, configured=False)

    async def _boom(**_kwargs):  # pragma: no cover - must not run
        raise AssertionError("approval service must not be consulted")

    monkeypatch.setattr(fresh_service, "ensure_approval", _boom)

    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=TOOL,
        idem_key="plain-permit-1",
    )
    assert permit["requires_human_approval"] is False

    resp = await client.post(
        "/mcp/messages",
        json=_invoke_body(provisioned, permit, "plain-invoke-1"),
        headers=provisioned["agent_headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["receipt"]["outcome"] == "success"
    assert resp.json()["result"]["receipt"]["approval_id"] is None


# ---------------------------------------------------------------------------
# Real mode against a scripted Sentinel
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_pending_then_approved_full_loop(
    client, clean_database, registered_tool, fresh_service, monkeypatch
):
    _sentinel_env(monkeypatch, simulated=False)
    fake = FakeSentinel(status="pending")
    monkeypatch.setattr(fresh_service, "_sentinel", lambda: fake)

    provisioned = await provision_agent_wallet(client)
    permit = await _approval_permit(client, provisioned, idem_key="real-permit-1")
    body = _invoke_body(provisioned, permit, "real-invoke-1")

    # First invoke: approval created in Sentinel, gate returns pending.
    first = await client.post(
        "/mcp/messages", json=body, headers=provisioned["agent_headers"]
    )
    assert first.status_code == 200
    error = first.json()["error"]
    assert error["code"] == -32005
    assert error["message"] == "human_approval_pending"
    assert error["data"]["approval_status"] == "pending"
    assert error["data"]["approval_id"].startswith("appr-")
    assert error["data"]["sentinel_action_id"].startswith("act_")
    assert len(fake.created) == 1
    # The request forwarded to Sentinel carries the governed context.
    sent = fake.created[0]
    assert sent["function_name"] == TOOL
    assert sent["arguments"]["permit_id"] == permit["permit_id"]

    # Nothing charged, no receipt written, and the idempotency key is free.
    assert await _ledger_debits(client, provisioned["agent_wallet_id"]) == 0

    # Retry while still pending: no second Sentinel approval is created.
    second = await client.post(
        "/mcp/messages", json=body, headers=provisioned["agent_headers"]
    )
    assert second.json()["error"]["message"] == "human_approval_pending"
    assert len(fake.created) == 1
    assert fake.polls == 1

    # Human approves in Sentinel; the SAME invoke (same key) now executes.
    fake.status = "approved"
    third = await client.post(
        "/mcp/messages", json=body, headers=provisioned["agent_headers"]
    )
    assert third.status_code == 200, third.text
    result = third.json()["result"]
    receipt = result["receipt"]
    assert receipt["outcome"] == "success"
    assert receipt["approval_id"] == error["data"]["approval_id"]
    assert receipt["ledger_entry_id"]
    assert await _ledger_debits(client, provisioned["agent_wallet_id"]) == 1

    # The receipt (with approval_id in its signed payload) verifies.
    verify = await client.post(
        "/v1/receipts/verify",
        json={"receipt_id": receipt["receipt_id"]},
        headers=BOOTSTRAP_HEADERS,
    )
    assert verify.status_code == 200
    assert verify.json()["valid"] is True

    # Replay of the completed invoke returns the same receipt, no new charge.
    replay = await client.post(
        "/mcp/messages", json=body, headers=provisioned["agent_headers"]
    )
    assert replay.json()["result"]["receipt"]["receipt_id"] == receipt["receipt_id"]
    assert await _ledger_debits(client, provisioned["agent_wallet_id"]) == 1


@pytest.mark.anyio
async def test_rejected_approval_is_terminal_and_replays(
    client, clean_database, registered_tool, fresh_service, monkeypatch
):
    _sentinel_env(monkeypatch, simulated=False)
    fake = FakeSentinel(status="pending")
    monkeypatch.setattr(fresh_service, "_sentinel", lambda: fake)

    provisioned = await provision_agent_wallet(client)
    permit = await _approval_permit(client, provisioned, idem_key="reject-permit-1")
    body = _invoke_body(provisioned, permit, "reject-invoke-1")

    pending = await client.post(
        "/mcp/messages", json=body, headers=provisioned["agent_headers"]
    )
    approval_id = pending.json()["error"]["data"]["approval_id"]

    fake.status = "rejected"
    denied = await client.post(
        "/mcp/messages", json=body, headers=provisioned["agent_headers"]
    )
    error = denied.json()["error"]
    assert error["code"] == -32003
    assert error["message"] == "human_approval_rejected"
    receipt = error["data"]["receipt"]
    assert receipt["outcome"] == "denied"
    assert receipt["approval_id"] == approval_id
    assert receipt["credits_charged"] == "0"
    assert await _ledger_debits(client, provisioned["agent_wallet_id"]) == 0

    # Terminal: the same key replays the denial without re-consulting Sentinel.
    polls_before = fake.polls
    replay = await client.post(
        "/mcp/messages", json=body, headers=provisioned["agent_headers"]
    )
    assert replay.json()["error"]["message"] == "human_approval_rejected"
    assert fake.polls == polls_before


@pytest.mark.anyio
async def test_locally_expired_approval_denies(
    client, clean_database, registered_tool, fresh_service, monkeypatch
):
    """Sentinel keeps timed-out approvals pending forever; we expire locally."""
    _sentinel_env(monkeypatch, simulated=False)
    fake = FakeSentinel(status="pending")
    monkeypatch.setattr(fresh_service, "_sentinel", lambda: fake)

    provisioned = await provision_agent_wallet(client)
    permit = await _approval_permit(client, provisioned, idem_key="expire-permit-1")
    body = _invoke_body(provisioned, permit, "expire-invoke-1")

    pending = await client.post(
        "/mcp/messages", json=body, headers=provisioned["agent_headers"]
    )
    approval_id = pending.json()["error"]["data"]["approval_id"]

    # Move the local expiry into the past.
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("UPDATE human_approvals SET expires_at = :past WHERE approval_id = :aid"),
            {"past": datetime(2000, 1, 1), "aid": approval_id},
        )
        await session.commit()

    # Even though Sentinel would now say "approved", local expiry wins —
    # the check runs before any remote poll.
    fake.status = "approved"
    denied = await client.post(
        "/mcp/messages", json=body, headers=provisioned["agent_headers"]
    )
    error = denied.json()["error"]
    assert error["message"] == "human_approval_expired"
    assert error["data"]["receipt"]["outcome"] == "denied"
    assert await _ledger_debits(client, provisioned["agent_wallet_id"]) == 0


@pytest.mark.anyio
async def test_sentinel_unreachable_is_retryable_not_terminal(
    client, clean_database, registered_tool, fresh_service, monkeypatch
):
    import httpx

    _sentinel_env(monkeypatch, simulated=False)
    fake = FakeSentinel(status="pending")
    fake.fail_with = httpx.ConnectError("no route to sentinel")
    monkeypatch.setattr(fresh_service, "_sentinel", lambda: fake)

    provisioned = await provision_agent_wallet(client)
    permit = await _approval_permit(client, provisioned, idem_key="outage-permit-1")
    body = _invoke_body(provisioned, permit, "outage-invoke-1")

    down = await client.post(
        "/mcp/messages", json=body, headers=provisioned["agent_headers"]
    )
    error = down.json()["error"]
    assert error["code"] == -32005
    assert error["message"] == "human_approval_unavailable"
    assert await _ledger_debits(client, provisioned["agent_wallet_id"]) == 0

    # Sentinel recovers: the same key proceeds instead of replaying an error.
    fake.fail_with = None
    fake.status = "approved"
    pending = await client.post(
        "/mcp/messages", json=body, headers=provisioned["agent_headers"]
    )
    # First successful contact creates the approval (pending), then approves.
    assert pending.json()["error"]["message"] == "human_approval_pending"
    done = await client.post(
        "/mcp/messages", json=body, headers=provisioned["agent_headers"]
    )
    assert done.json()["result"]["receipt"]["outcome"] == "success"


# ---------------------------------------------------------------------------
# Signature coverage
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_tampering_with_permit_flag_invalidates_signature(
    client, clean_database, registered_tool, fresh_service, monkeypatch
):
    _sentinel_env(monkeypatch, simulated=True, configured=False)

    provisioned = await provision_agent_wallet(client)
    permit = await _approval_permit(client, provisioned, idem_key="tamper-permit-1")

    # Flip the stored flag off — as if a DB tamperer disabled the gate.
    factory = get_session_factory()
    async with factory() as session:
        model = await session.get(PermitModel, permit["permit_id"])
        model.requires_human_approval = False
        session.add(model)
        await session.commit()

    resp = await client.post(
        "/mcp/messages",
        json=_invoke_body(provisioned, permit, "tamper-invoke-1"),
        headers=provisioned["agent_headers"],
    )
    error = resp.json()["error"]
    assert error["message"] == "permit_signature_invalid"


@pytest.mark.anyio
async def test_tampering_with_receipt_approval_id_invalidates_signature(
    client, clean_database, registered_tool, fresh_service, monkeypatch
):
    _sentinel_env(monkeypatch, simulated=True, configured=False)

    provisioned = await provision_agent_wallet(client)
    permit = await _approval_permit(client, provisioned, idem_key="rtamper-permit-1")
    resp = await client.post(
        "/mcp/messages",
        json=_invoke_body(provisioned, permit, "rtamper-invoke-1"),
        headers=provisioned["agent_headers"],
    )
    receipt = resp.json()["result"]["receipt"]

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("UPDATE receipts SET approval_id = NULL WHERE receipt_id = :rid"),
            {"rid": receipt["receipt_id"]},
        )
        await session.commit()

    verify = await client.post(
        "/v1/receipts/verify",
        json={"receipt_id": receipt["receipt_id"]},
        headers=BOOTSTRAP_HEADERS,
    )
    assert verify.status_code == 200
    assert verify.json()["valid"] is False


# ---------------------------------------------------------------------------
# Service-level unit coverage
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_service_raises_unavailable_on_poll_failure(
    clean_database, fresh_service, monkeypatch, client
):
    import httpx

    _sentinel_env(monkeypatch, simulated=False)
    fake = FakeSentinel(status="pending")
    monkeypatch.setattr(fresh_service, "_sentinel", lambda: fake)

    provisioned = await provision_agent_wallet(client)
    permit = await _approval_permit(client, provisioned, idem_key="svc-permit-1")

    check = await fresh_service.ensure_approval(
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        tool_name=TOOL,
        idempotency_key="svc-key-1",
        arguments={},
        estimated_credits=Decimal("2"),
    )
    assert check.status == "pending"

    fake.fail_with = httpx.ReadTimeout("slow sentinel")
    with pytest.raises(HumanApprovalUnavailableError):
        await fresh_service.ensure_approval(
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=permit["permit_id"],
            tool_name=TOOL,
            idempotency_key="svc-key-1",
            arguments={},
            estimated_credits=Decimal("2"),
        )


@pytest.mark.anyio
async def test_service_4xx_from_sentinel_is_terminal(
    clean_database, fresh_service, monkeypatch, client
):
    import httpx

    _sentinel_env(monkeypatch, simulated=False)
    request = httpx.Request("POST", "https://sentinel.test/v1/approvals")
    response = httpx.Response(400, request=request, text="approvers must be set")
    fake = FakeSentinel()
    fake.fail_with = httpx.HTTPStatusError("400", request=request, response=response)
    monkeypatch.setattr(fresh_service, "_sentinel", lambda: fake)

    provisioned = await provision_agent_wallet(client)
    permit = await _approval_permit(client, provisioned, idem_key="svc4xx-permit-1")

    with pytest.raises(HumanApprovalError) as excinfo:
        await fresh_service.ensure_approval(
            wallet_id=provisioned["agent_wallet_id"],
            permit_id=permit["permit_id"],
            tool_name=TOOL,
            idempotency_key="svc4xx-key-1",
            arguments={},
            estimated_credits=Decimal("2"),
        )
    assert excinfo.value.reason == "human_approval_request_rejected"


def test_sim_flag_is_registered_with_runtime_mode():
    from app.core.runtime_mode import SERVICE_NAMES, simulation_settings_field

    assert "human_approval" in SERVICE_NAMES
    assert (
        simulation_settings_field("human_approval") == "SIMULATION_MODE_HUMAN_APPROVAL"
    )
