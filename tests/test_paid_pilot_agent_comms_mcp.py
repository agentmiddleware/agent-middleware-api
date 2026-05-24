from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db.database import get_session_factory
from app.db.models import AgentCommsMessageModel
from app.main import app
from app.services.service_registry import get_service_registry
from tests.test_trust_helpers import (
    BOOTSTRAP_HEADERS,
    create_tool_permit,
    provision_agent_wallet,
)

PAID_PILOT_TOOL = "agent-comms-send"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def agent_comms_mode():
    settings = get_settings()
    saved = settings.SIMULATION_MODE_AGENT_COMMS
    registry = get_service_registry()
    yield settings
    settings.SIMULATION_MODE_AGENT_COMMS = saved
    registry.unregister_local(PAID_PILOT_TOOL)


async def _register_receiver(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/v1/comms/agents",
        json={"name": "paid-pilot-receiver", "capabilities": ["trust-intake"]},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()["agent_id"]


def _mcp_call(
    *,
    wallet_id: str,
    permit_id: str,
    idempotency_key: str,
    receiver_id: str,
) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": "paid-pilot-agent-comms-call",
        "method": "tools/call",
        "params": {
            "name": PAID_PILOT_TOOL,
            "arguments": {
                "to_agent": receiver_id,
                "subject": "Pilot trust proof",
                "body": {"intent": "prove real governed side effect"},
                "_mcp_context": {"wallet_id": "attacker-controlled"},
            },
            "mcpContext": {
                "wallet_id": wallet_id,
                "permit_id": permit_id,
                "idempotency_key": idempotency_key,
            },
        },
    }


async def _agent_comms_rows(message_id: str) -> list[AgentCommsMessageModel]:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(AgentCommsMessageModel).where(
                AgentCommsMessageModel.message_id == message_id
            )
        )
        return list(result.scalars().all())


@pytest.mark.anyio
async def test_paid_pilot_tool_discovered_only_in_real_agent_comms_mode(
    client,
    clean_database,
    agent_comms_mode,
):
    agent_comms_mode.SIMULATION_MODE_AGENT_COMMS = False

    real_response = await client.get("/mcp/tools.json", headers=BOOTSTRAP_HEADERS)
    assert real_response.status_code == 200
    tools = real_response.json()["tools"]
    tool = next(item for item in tools if item["name"] == PAID_PILOT_TOOL)
    assert tool["annotations"]["category"] == "agent_comms"
    assert tool["annotations"]["unitName"] == "message"
    assert "_mcp_context" not in tool["inputSchema"]["properties"]

    agent_comms_mode.SIMULATION_MODE_AGENT_COMMS = True

    sim_response = await client.get("/mcp/tools.json", headers=BOOTSTRAP_HEADERS)
    assert sim_response.status_code == 200
    assert PAID_PILOT_TOOL not in {
        item["name"] for item in sim_response.json()["tools"]
    }


@pytest.mark.anyio
async def test_paid_pilot_agent_comms_tool_proves_trust_loop(
    client,
    clean_database,
    agent_comms_mode,
):
    agent_comms_mode.SIMULATION_MODE_AGENT_COMMS = False
    provisioned = await provision_agent_wallet(client)
    receiver_id = await _register_receiver(client, provisioned["agent_headers"])
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=PAID_PILOT_TOOL,
        idem_key="paid-pilot-agent-comms-permit",
    )
    body = _mcp_call(
        wallet_id=provisioned["agent_wallet_id"],
        permit_id=permit["permit_id"],
        idempotency_key="paid-pilot-agent-comms-invoke",
        receiver_id=receiver_id,
    )

    response = await client.post(
        "/mcp/messages",
        json=body,
        headers=provisioned["agent_headers"],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["isError"] is False
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["durable"] is True
    assert result["from_agent"] == provisioned["agent_wallet_id"]
    assert result["to_agent"] == receiver_id
    assert result["payload_hash"]
    receipt = payload["result"]["receipt"]
    assert receipt["tool"] == PAID_PILOT_TOOL
    assert receipt["outcome"] == "success"
    assert receipt["ledger_entry_id"]

    rows = await _agent_comms_rows(result["message_id"])
    assert len(rows) == 1
    assert rows[0].from_agent == provisioned["agent_wallet_id"]
    assert rows[0].to_agent == receiver_id
    assert rows[0].payload_hash == result["payload_hash"]

    replay = await client.post(
        "/mcp/messages",
        json=body,
        headers=provisioned["agent_headers"],
    )
    assert replay.status_code == 200
    replay_payload = replay.json()
    assert (
        replay_payload["result"]["receipt"]["receipt_id"]
        == receipt["receipt_id"]
    )
    replay_result = json.loads(replay_payload["result"]["content"][0]["text"])
    assert replay_result["message_id"] == result["message_id"]
    assert len(await _agent_comms_rows(result["message_id"])) == 1

    ledger = await client.get(
        f"/v1/billing/ledger/{provisioned['agent_wallet_id']}",
        headers=provisioned["agent_headers"],
    )
    assert ledger.status_code == 200
    debits = [
        entry
        for entry in ledger.json()["entries"]
        if entry["service_category"] == "agent_comms"
        and PAID_PILOT_TOOL in entry.get("description", "")
    ]
    assert len(debits) == 1

    inbox = await client.get(
        "/v1/agent-comms/inbox",
        params={"agent_id": receiver_id},
        headers=provisioned["agent_headers"],
    )
    assert inbox.status_code == 200
    assert any(
        message["message_id"] == result["message_id"]
        for message in inbox.json()["messages"]
    )

    evidence = await client.get(
        f"/v1/evidence/{receipt['receipt_id']}",
        headers=provisioned["agent_headers"],
    )
    assert evidence.status_code == 200
    bundle = evidence.json()
    assert bundle["valid"] is True
    assert bundle["ledger_entry"]["entry_id"] == receipt["ledger_entry_id"]
    assert bundle["verification"]["receipt_signature"] == "ok"
    assert bundle["verification"]["permit_signature"] == "ok"
    assert bundle["verification"]["audit_chain"] == "ok"

    audit = await client.get(
        (
            f"/v1/audit/events?wallet_id={provisioned['agent_wallet_id']}"
            f"&tool={PAID_PILOT_TOOL}"
        ),
        headers=BOOTSTRAP_HEADERS,
    )
    assert audit.status_code == 200
    audit_events = audit.json()["events"]
    assert len(audit_events) == 1
    metadata = audit_events[0]["metadata"]
    assert metadata["permit_id"] == permit["permit_id"]
    assert metadata["idempotency_key"] == "paid-pilot-agent-comms-invoke"
    assert metadata["ledger_entry_id"] == debits[0]["entry_id"]
    assert metadata["request_hash"]


@pytest.mark.anyio
async def test_paid_pilot_permit_denies_out_of_scope_tool(
    client,
    clean_database,
    agent_comms_mode,
):
    agent_comms_mode.SIMULATION_MODE_AGENT_COMMS = False
    provisioned = await provision_agent_wallet(client)
    permit = await create_tool_permit(
        client,
        wallet_id=provisioned["agent_wallet_id"],
        key_id=provisioned["key_id"],
        tool_name=PAID_PILOT_TOOL,
        idem_key="paid-pilot-denial-permit",
    )

    response = await client.post(
        "/mcp/messages",
        json={
            "jsonrpc": "2.0",
            "id": "paid-pilot-denial",
            "method": "tools/call",
            "params": {
                "name": "data-indexer",
                "arguments": {"document": "not allowed"},
                "mcpContext": {
                    "wallet_id": provisioned["agent_wallet_id"],
                    "permit_id": permit["permit_id"],
                    "idempotency_key": "paid-pilot-denial",
                },
            },
        },
        headers=provisioned["agent_headers"],
    )

    assert response.status_code == 200
    error = response.json()["error"]
    assert error["message"] == "permit_tool_not_allowed"
    receipt = error["data"]["receipt"]
    assert receipt["outcome"] == "denied"
    assert receipt["credits_charged"] == "0"
    assert receipt["ledger_entry_id"] is None

    ledger = await client.get(
        f"/v1/billing/ledger/{provisioned['agent_wallet_id']}",
        headers=provisioned["agent_headers"],
    )
    assert ledger.status_code == 200
    assert [
        entry
        for entry in ledger.json()["entries"]
        if entry["service_category"] == "agent_comms"
    ] == []
