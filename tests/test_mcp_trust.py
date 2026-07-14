from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.database import get_session_factory
from app.db.models import IdempotencyRecordModel
from app.main import app
from app.schemas.billing import ServiceCategory
from app.services.idempotency import (
    IdempotencyInProgressError,
    get_idempotency_service,
)
from app.services.receipts import ReceiptService
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import create_tool_permit, provision_agent_wallet


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_governed_mcp_invoke_returns_receipt_and_replay_does_not_double_charge(
    client,
    clean_database,
):
    provisioned = await provision_agent_wallet(client)
    registry = get_service_registry()

    def trust_echo(message: str = "ok") -> dict:
        return {"message": message}

    registry.register_local(
        service_id="trust-echo",
        name="Trust Echo",
        description="Governed trust test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=trust_echo,
        credits_per_unit=2.0,
        unit_name="call",
    )
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name="trust-echo",
        )
        body = {
            "jsonrpc": "2.0",
            "id": "trust-call-1",
            "method": "tools/call",
            "params": {
                "name": "trust-echo",
                "arguments": {"message": "hello"},
                "mcpContext": {
                    "wallet_id": provisioned["agent_wallet_id"],
                    "permit_id": permit["permit_id"],
                    "idempotency_key": "trust-invoke-1",
                },
            },
        }
        first = await client.post(
            "/mcp/messages",
            json=body,
            headers=provisioned["agent_headers"],
        )
        assert first.status_code == 200
        first_payload = first.json()
        receipt = first_payload["result"]["receipt"]
        assert receipt["permit_id"] == permit["permit_id"]
        assert receipt["ledger_entry_id"]
        assert receipt["outcome"] == "success"

        replay = await client.post(
            "/mcp/messages",
            json=body,
            headers=provisioned["agent_headers"],
        )
        assert replay.status_code == 200
        assert replay.json()["result"]["receipt"]["receipt_id"] == receipt["receipt_id"]

        ledger_resp = await client.get(
            f"/v1/billing/ledger/{provisioned['agent_wallet_id']}",
            headers=provisioned["agent_headers"],
        )
        debits = [
            entry for entry in ledger_resp.json()["entries"]
            if entry["service_category"] == "agent_comms"
            and "trust-echo" in entry["description"]
        ]
        assert len(debits) == 1
    finally:
        registry.unregister_local("trust-echo")


@pytest.mark.anyio
async def test_http_invoke_tool_governed_flow_returns_receipt(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    registry = get_service_registry()
    registry.register_local(
        service_id="http-invoke-tool",
        name="HTTP Invoke Tool",
        description="Governed HTTP invoke test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=lambda message="ok": {"message": message},
        credits_per_unit=2.0,
        unit_name="call",
    )
    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name="http-invoke-tool",
        )
        resp = await client.post(
            "/mcp/tools/http-invoke-tool/invoke",
            json={
                "name": "http-invoke-tool",
                "arguments": {"message": "hi"},
                "mcp_context": {
                    "wallet_id": provisioned["agent_wallet_id"],
                    "permit_id": permit["permit_id"],
                    "idempotency_key": "http-invoke-1",
                },
            },
            headers=provisioned["agent_headers"],
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["isError"] is False
        assert body["receipt"]["permit_id"] == permit["permit_id"]
        assert body["receipt"]["outcome"] == "success"

        # Out-of-scope tool over the same HTTP route is denied with 403.
        registry.register_local(
            service_id="http-blocked-tool",
            name="HTTP Blocked Tool",
            description="Outside the permit",
            category=ServiceCategory.AGENT_COMMS,
            func=lambda: {"ran": True},
            credits_per_unit=2.0,
            unit_name="call",
        )
        denied = await client.post(
            "/mcp/tools/http-blocked-tool/invoke",
            json={
                "name": "http-blocked-tool",
                "arguments": {},
                "mcp_context": {
                    "wallet_id": provisioned["agent_wallet_id"],
                    "permit_id": permit["permit_id"],
                    "idempotency_key": "http-denied-1",
                },
            },
            headers=provisioned["agent_headers"],
        )
        assert denied.status_code == 403
        assert denied.json()["detail"]["error"] == "permit_tool_not_allowed"
    finally:
        registry.unregister_local("http-invoke-tool")
        registry.unregister_local("http-blocked-tool")


@pytest.mark.anyio
async def test_governed_mcp_requires_idempotency_key(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    registry = get_service_registry()
    registry.register_local(
        service_id="missing-idem-tool",
        name="Missing Idempotency Tool",
        description="Governed trust test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=lambda: {"ok": True},
        credits_per_unit=2.0,
        unit_name="call",
    )
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="missing-idem-tool",
    )
    try:
        resp = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": "trust-call-2",
                "method": "tools/call",
                "params": {
                    "name": "missing-idem-tool",
                    "arguments": {},
                    "mcpContext": {
                        "wallet_id": provisioned["agent_wallet_id"],
                        "permit_id": permit["permit_id"],
                    },
                },
            },
            headers=provisioned["agent_headers"],
        )
    finally:
        registry.unregister_local("missing-idem-tool")
    assert resp.status_code == 200
    assert resp.json()["error"]["message"] == "idempotency_key_required"


@pytest.mark.anyio
async def test_governed_mcp_rejects_in_progress_idempotency_without_charge(
    client,
    clean_database,
):
    provisioned = await provision_agent_wallet(client)
    calls = {"count": 0}
    registry = get_service_registry()

    def in_progress_tool() -> dict:
        calls["count"] += 1
        return {"ok": True}

    registry.register_local(
        service_id="in-progress-idem-tool",
        name="In Progress Idempotency Tool",
        description="Governed idempotency in-progress test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=in_progress_tool,
        credits_per_unit=2.0,
        unit_name="call",
    )
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="in-progress-idem-tool",
        idem_key="in-progress-mcp-permit-create-1",
    )
    body = {
        "jsonrpc": "2.0",
        "id": "in-progress-idem-call",
        "method": "tools/call",
        "params": {
            "name": "in-progress-idem-tool",
            "arguments": {},
            "mcpContext": {
                "wallet_id": provisioned["agent_wallet_id"],
                "permit_id": permit["permit_id"],
                "idempotency_key": "in-progress-mcp-key",
            },
        },
    }
    await get_idempotency_service().begin(
        wallet_id=provisioned["agent_wallet_id"],
        endpoint="/mcp/messages",
        idempotency_key="in-progress-mcp-key",
        request_payload=body,
    )
    try:
        resp = await client.post(
            "/mcp/messages",
            json=body,
            headers=provisioned["agent_headers"],
        )
    finally:
        registry.unregister_local("in-progress-idem-tool")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["error"]["code"] == -32003
    assert payload["error"]["message"] == "idempotency_in_progress"
    assert calls["count"] == 0
    ledger_resp = await client.get(
        f"/v1/billing/ledger/{provisioned['agent_wallet_id']}",
        headers=provisioned["agent_headers"],
    )
    debits = [
        entry
        for entry in ledger_resp.json()["entries"]
        if entry["service_category"] == "agent_comms"
        and "in-progress-idem-tool" in entry["description"]
    ]
    assert debits == []


@pytest.mark.anyio
async def test_out_of_scope_governed_mcp_denial_returns_receipt(
    client,
    clean_database,
):
    provisioned = await provision_agent_wallet(client)
    registry = get_service_registry()
    registry.register_local(
        service_id="blocked-trust-tool",
        name="Blocked Trust Tool",
        description="Governed trust denial test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=lambda: {"ok": True},
        credits_per_unit=2.0,
        unit_name="call",
    )
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="allowed-trust-tool",
        idem_key="permit-denial-create-1",
    )
    try:
        resp = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": "trust-denial-1",
                "method": "tools/call",
                "params": {
                    "name": "blocked-trust-tool",
                    "arguments": {},
                    "mcpContext": {
                        "wallet_id": provisioned["agent_wallet_id"],
                        "permit_id": permit["permit_id"],
                        "idempotency_key": "trust-denial-invoke-1",
                    },
                },
            },
            headers=provisioned["agent_headers"],
        )

        replay = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": "trust-denial-1",
                "method": "tools/call",
                "params": {
                    "name": "blocked-trust-tool",
                    "arguments": {},
                    "mcpContext": {
                        "wallet_id": provisioned["agent_wallet_id"],
                        "permit_id": permit["permit_id"],
                        "idempotency_key": "trust-denial-invoke-1",
                    },
                },
            },
            headers=provisioned["agent_headers"],
        )
    finally:
        registry.unregister_local("blocked-trust-tool")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["error"]["message"] == "permit_tool_not_allowed"
    receipt = payload["error"]["data"]["receipt"]
    assert receipt["permit_id"] == permit["permit_id"]
    assert receipt["outcome"] == "denied"
    assert receipt["ledger_entry_id"] is None
    assert receipt["credits_charged"] == "0"

    assert replay.status_code == 200
    replay_payload = replay.json()
    assert "result" not in replay_payload
    assert replay_payload["error"]["message"] == "permit_tool_not_allowed"
    assert (
        replay_payload["error"]["data"]["receipt"]["receipt_id"]
        == receipt["receipt_id"]
    )


@pytest.mark.anyio
async def test_governed_policy_denial_returns_receipt(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    registry = get_service_registry()
    registry.register_local(
        service_id="policy-denied-trust-tool",
        name="Policy Denied Trust Tool",
        description="Governed trust policy denial test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=lambda: {"ok": True},
        credits_per_unit=2.0,
        unit_name="call",
    )
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="policy-denied-trust-tool",
        idem_key="policy-denial-permit-create-1",
    )
    policy_resp = await client.post(
        "/v1/policies",
        json={
            "wallet_id": provisioned["agent_wallet_id"],
            "name": "Governed deny one tool",
            "allowed_tools": ["some-other-tool"],
        },
        headers={"X-API-Key": "test-key"},
    )
    assert policy_resp.status_code == 201
    body = {
        "jsonrpc": "2.0",
        "id": "policy-denial-trust-call",
        "method": "tools/call",
        "params": {
            "name": "policy-denied-trust-tool",
            "arguments": {},
            "mcpContext": {
                "wallet_id": provisioned["agent_wallet_id"],
                "permit_id": permit["permit_id"],
                "idempotency_key": "policy-denial-trust-invoke-1",
            },
        },
    }
    try:
        resp = await client.post(
            "/mcp/messages",
            json=body,
            headers=provisioned["agent_headers"],
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["error"]["message"] == "tool_not_allowed"
        receipt = payload["error"]["data"]["receipt"]
        assert receipt["outcome"] == "denied"
        assert receipt["credits_charged"] == "0"

        replay = await client.post(
            "/mcp/messages",
            json=body,
            headers=provisioned["agent_headers"],
        )
        assert replay.json()["error"]["data"]["receipt"]["receipt_id"] == receipt[
            "receipt_id"
        ]
    finally:
        registry.unregister_local("policy-denied-trust-tool")


@pytest.mark.anyio
async def test_governed_tool_failure_returns_refunded_receipt(client, clean_database):
    provisioned = await provision_agent_wallet(client)
    registry = get_service_registry()

    def failing_tool() -> dict:
        raise RuntimeError("tool exploded")

    registry.register_local(
        service_id="failing-trust-tool",
        name="Failing Trust Tool",
        description="Governed trust failure receipt test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=failing_tool,
        credits_per_unit=2.0,
        unit_name="call",
    )
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name="failing-trust-tool",
        idem_key="failing-trust-permit-create-1",
    )
    try:
        resp = await client.post(
            "/mcp/messages",
            json={
                "jsonrpc": "2.0",
                "id": "failing-trust-call",
                "method": "tools/call",
                "params": {
                    "name": "failing-trust-tool",
                    "arguments": {},
                    "mcpContext": {
                        "wallet_id": provisioned["agent_wallet_id"],
                        "permit_id": permit["permit_id"],
                        "idempotency_key": "failing-trust-invoke-1",
                    },
                },
            },
            headers=provisioned["agent_headers"],
        )
    finally:
        registry.unregister_local("failing-trust-tool")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["error"]["message"] == "tool exploded"
    receipt = payload["error"]["data"]["receipt"]
    assert receipt["outcome"] == "failed_refunded"
    assert receipt["ledger_entry_id"]
    assert receipt["credits_charged"] == "0"


async def _age_idempotency_record(wallet_id: str, idempotency_key: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(IdempotencyRecordModel).where(
                IdempotencyRecordModel.wallet_id == wallet_id,
                IdempotencyRecordModel.endpoint == "/mcp/messages",
                IdempotencyRecordModel.idempotency_key == idempotency_key,
            )
        )
        record = result.scalar_one()
        record.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
        session.add(record)
        await session.commit()


@pytest.mark.anyio
async def test_governed_mcp_finalize_retries_on_transient_receipt_failure(
    client, clean_database
):
    """A transient failure writing the receipt must not turn a successful,
    already-charged tool call into an error -- the finalize sequence should
    retry and still return the real receipt."""
    provisioned = await provision_agent_wallet(client)
    registry = get_service_registry()

    def flaky_finalize_tool() -> dict:
        return {"ok": True}

    registry.register_local(
        service_id="flaky-finalize-tool",
        name="Flaky Finalize Tool",
        description="Governed trust finalize-retry test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=flaky_finalize_tool,
        credits_per_unit=2.0,
        unit_name="call",
    )
    call_count = {"n": 0}
    original_create_receipt = ReceiptService.create_receipt

    async def flaky_create_receipt(self, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] <= 2:
            raise RuntimeError("transient db hiccup")
        return await original_create_receipt(self, *args, **kwargs)

    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name="flaky-finalize-tool",
            idem_key="flaky-finalize-permit-create-1",
        )
        body = {
            "jsonrpc": "2.0",
            "id": "flaky-finalize-call",
            "method": "tools/call",
            "params": {
                "name": "flaky-finalize-tool",
                "arguments": {},
                "mcpContext": {
                    "wallet_id": provisioned["agent_wallet_id"],
                    "permit_id": permit["permit_id"],
                    "idempotency_key": "flaky-finalize-invoke-1",
                },
            },
        }
        with patch.object(ReceiptService, "create_receipt", flaky_create_receipt):
            resp = await client.post(
                "/mcp/messages", json=body, headers=provisioned["agent_headers"]
            )

        assert resp.status_code == 200
        payload = resp.json()
        receipt = payload["result"]["receipt"]
        assert receipt["outcome"] == "success"
        assert call_count["n"] == 3

        ledger_resp = await client.get(
            f"/v1/billing/ledger/{provisioned['agent_wallet_id']}",
            headers=provisioned["agent_headers"],
        )
        debits = [
            e
            for e in ledger_resp.json()["entries"]
            if e["service_category"] == "agent_comms"
        ]
        # Exactly one charge landed despite the two failed finalize attempts:
        # retries reuse the already-created receipt rather than recharging.
        assert len(debits) == 1
    finally:
        registry.unregister_local("flaky-finalize-tool")


@pytest.mark.anyio
async def test_reconcile_stuck_records_repairs_charged_but_unfinalized_record(
    client, clean_database
):
    """If finalize exhausts all retries after the receipt was already
    written (e.g. a crash right before idempotency-complete), the record is
    left charged-but-stuck. reconcile_stuck_records must repair it from the
    receipt so a later retry replays cleanly instead of hanging forever."""
    provisioned = await provision_agent_wallet(client)
    registry = get_service_registry()

    def crash_after_receipt_tool() -> dict:
        return {"ok": True}

    registry.register_local(
        service_id="crash-after-receipt-tool",
        name="Crash After Receipt Tool",
        description="Governed trust reconciliation test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=crash_after_receipt_tool,
        credits_per_unit=2.0,
        unit_name="call",
    )

    async def always_fail_complete(self, *args, **kwargs):
        raise RuntimeError("process died before idempotency-complete")

    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name="crash-after-receipt-tool",
            idem_key="crash-after-receipt-permit-create-1",
        )
        idempotency_key = "crash-after-receipt-invoke-1"
        body = {
            "jsonrpc": "2.0",
            "id": "crash-after-receipt-call",
            "method": "tools/call",
            "params": {
                "name": "crash-after-receipt-tool",
                "arguments": {},
                "mcpContext": {
                    "wallet_id": provisioned["agent_wallet_id"],
                    "permit_id": permit["permit_id"],
                    "idempotency_key": idempotency_key,
                },
            },
        }
        idem = get_idempotency_service()
        with patch.object(
            type(idem), "complete", always_fail_complete
        ):
            resp = await client.post(
                "/mcp/messages", json=body, headers=provisioned["agent_headers"]
            )
        # All 3 finalize attempts failed at the complete() step -> surfaces as
        # a JSON-RPC error, not a silent success.
        assert resp.status_code == 200
        assert resp.json()["error"]["code"] == -32603

        await _age_idempotency_record(
            provisioned["agent_wallet_id"], idempotency_key
        )

        repaired, needs_review = await idem.reconcile_stuck_records(idle_seconds=900)
        assert repaired == 1
        assert needs_review == 0

        # The stuck record now replays instead of raising IdempotencyInProgressError.
        replay = await client.post(
            "/mcp/messages", json=body, headers=provisioned["agent_headers"]
        )
        assert replay.status_code == 200
        replay_payload = replay.json()
        assert "error" not in replay_payload or replay_payload.get("error") is None
        assert replay_payload["result"]["reconciled"] is True
        assert replay_payload["result"]["receipt_id"]

        # Exactly one charge landed for the whole scenario.
        ledger_resp = await client.get(
            f"/v1/billing/ledger/{provisioned['agent_wallet_id']}",
            headers=provisioned["agent_headers"],
        )
        debits = [
            e
            for e in ledger_resp.json()["entries"]
            if e["service_category"] == "agent_comms"
        ]
        assert len(debits) == 1
    finally:
        registry.unregister_local("crash-after-receipt-tool")


@pytest.mark.anyio
async def test_reconcile_stuck_records_flags_charge_with_no_receipt_for_review(
    client, clean_database
):
    """If the charge landed but the receipt itself was never created (a more
    severe crash), there is nothing safe to auto-repair -- the original tool
    response was never persisted. reconcile_stuck_records must leave it
    untouched and report it separately rather than fabricate a receipt."""
    provisioned = await provision_agent_wallet(client)
    registry = get_service_registry()

    def crash_before_receipt_tool() -> dict:
        return {"ok": True}

    registry.register_local(
        service_id="crash-before-receipt-tool",
        name="Crash Before Receipt Tool",
        description="Governed trust reconciliation test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=crash_before_receipt_tool,
        credits_per_unit=2.0,
        unit_name="call",
    )

    async def always_fail_create_receipt(self, *args, **kwargs):
        raise RuntimeError("process died before receipt could be written")

    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name="crash-before-receipt-tool",
            idem_key="crash-before-receipt-permit-create-1",
        )
        idempotency_key = "crash-before-receipt-invoke-1"
        body = {
            "jsonrpc": "2.0",
            "id": "crash-before-receipt-call",
            "method": "tools/call",
            "params": {
                "name": "crash-before-receipt-tool",
                "arguments": {},
                "mcpContext": {
                    "wallet_id": provisioned["agent_wallet_id"],
                    "permit_id": permit["permit_id"],
                    "idempotency_key": idempotency_key,
                },
            },
        }
        with patch.object(
            ReceiptService, "create_receipt", always_fail_create_receipt
        ):
            resp = await client.post(
                "/mcp/messages", json=body, headers=provisioned["agent_headers"]
            )
        assert resp.status_code == 200
        assert resp.json()["error"]["code"] == -32603

        await _age_idempotency_record(
            provisioned["agent_wallet_id"], idempotency_key
        )

        idem = get_idempotency_service()
        repaired, needs_review = await idem.reconcile_stuck_records(idle_seconds=900)
        assert repaired == 0
        assert needs_review == 1

        # Still stuck: a retry with the same key correctly still fails closed
        # rather than silently fabricating success.
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.wallet_id
                    == provisioned["agent_wallet_id"],
                    IdempotencyRecordModel.endpoint == "/mcp/messages",
                    IdempotencyRecordModel.idempotency_key == idempotency_key,
                )
            )
            record = result.scalar_one()
            assert record.response_json is None
        with pytest.raises(IdempotencyInProgressError):
            await idem.begin(
                wallet_id=provisioned["agent_wallet_id"],
                endpoint="/mcp/messages",
                idempotency_key=idempotency_key,
                # Must match the exact payload the router hashed originally
                # (the whole JSON-RPC body -- see handle_messages, which
                # passes request_payload=body), or this looks like key reuse
                # with a different request instead of a genuine retry.
                request_payload=body,
            )
    finally:
        registry.unregister_local("crash-before-receipt-tool")


@pytest.mark.anyio
async def test_reconcile_stuck_records_preserves_failed_outcome(
    client, clean_database
):
    """A crash can leave a stuck idempotency record whose matching receipt
    records a FAILURE (e.g. the tool raised, the charge was refunded, and
    _finalize_governed_denial crashed before idem.complete()). Reconciliation
    must replay that as the failure it was, not a fabricated 200 success."""
    provisioned = await provision_agent_wallet(client)
    registry = get_service_registry()

    def exploding_tool() -> dict:
        raise RuntimeError("tool exploded before finalize crash")

    registry.register_local(
        service_id="crash-in-denial-tool",
        name="Crash In Denial Finalize Tool",
        description="Governed trust reconciliation outcome-fidelity test tool",
        category=ServiceCategory.AGENT_COMMS,
        func=exploding_tool,
        credits_per_unit=2.0,
        unit_name="call",
    )

    idem = get_idempotency_service()
    original_complete = type(idem).complete

    async def complete_only_fails_for_this_key(self, *, idempotency_key, **kwargs):
        if idempotency_key == "crash-in-denial-invoke-1":
            raise RuntimeError("process died before idempotency-complete")
        return await original_complete(self, idempotency_key=idempotency_key, **kwargs)

    try:
        permit = await create_tool_permit(
            client,
            wallet_id=provisioned["agent_wallet_id"],
            key_id=provisioned["key_id"],
            tool_name="crash-in-denial-tool",
            idem_key="crash-in-denial-permit-create-1",
        )
        idempotency_key = "crash-in-denial-invoke-1"
        body = {
            "jsonrpc": "2.0",
            "id": "crash-in-denial-call",
            "method": "tools/call",
            "params": {
                "name": "crash-in-denial-tool",
                "arguments": {},
                "mcpContext": {
                    "wallet_id": provisioned["agent_wallet_id"],
                    "permit_id": permit["permit_id"],
                    "idempotency_key": idempotency_key,
                },
            },
        }
        with patch.object(
            type(idem), "complete", complete_only_fails_for_this_key
        ):
            resp = await client.post(
                "/mcp/messages", json=body, headers=provisioned["agent_headers"]
            )
        assert resp.status_code == 200
        assert resp.json()["error"]["code"] == -32603

        await _age_idempotency_record(
            provisioned["agent_wallet_id"], idempotency_key
        )

        repaired, needs_review = await idem.reconcile_stuck_records(idle_seconds=900)
        assert repaired == 1
        assert needs_review == 0

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(IdempotencyRecordModel).where(
                    IdempotencyRecordModel.wallet_id
                    == provisioned["agent_wallet_id"],
                    IdempotencyRecordModel.endpoint == "/mcp/messages",
                    IdempotencyRecordModel.idempotency_key == idempotency_key,
                )
            )
            record = result.scalar_one()
            import json as _json

            reconciled = _json.loads(record.response_json)
            # The bug: this used to always be a bare 200 success regardless
            # of what the receipt actually recorded.
            assert reconciled["outcome"] == "failed_refunded"
            assert reconciled["isError"] is True
            assert record.status_code == 500

        # The wallet was refunded -- no net charge from the whole scenario.
        ledger_resp = await client.get(
            f"/v1/billing/ledger/{provisioned['agent_wallet_id']}",
            headers=provisioned["agent_headers"],
        )
        entries = [
            e
            for e in ledger_resp.json()["entries"]
            if e["service_category"] == "agent_comms"
        ]
        net = sum(e["amount"] for e in entries)
        assert net == 0
    finally:
        registry.unregister_local("crash-in-denial-tool")
