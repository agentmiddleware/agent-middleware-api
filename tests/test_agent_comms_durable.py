"""Contract: durable agent comms (DB + /v1/agent-comms)."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db.database import get_session_factory
from app.db.models import AgentCommsMessageModel
from app.main import app

HEADERS = {"X-API-Key": "test-key"}


async def create_wallet_key(client: AsyncClient, name: str) -> dict[str, str]:
    wallet_resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": name, "email": f"{name}@test.example"},
        headers=HEADERS,
    )
    assert wallet_resp.status_code == 201
    wallet_id = wallet_resp.json()["wallet_id"]

    key_resp = await client.post(
        "/v1/api-keys",
        json={"wallet_id": wallet_id, "key_name": name},
        headers=HEADERS,
    )
    assert key_resp.status_code == 201
    return {"X-API-Key": key_resp.json()["api_key"]}


@pytest.fixture(autouse=True)
def _restore_agent_comms_sim():
    settings = get_settings()
    saved = settings.SIMULATION_MODE_AGENT_COMMS
    yield
    settings.SIMULATION_MODE_AGENT_COMMS = saved


@pytest.mark.anyio
async def test_durable_send_persists_row_and_inbox_lists():
    settings = get_settings()
    settings.SIMULATION_MODE_AGENT_COMMS = False
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        s = await client.post(
            "/v1/comms/agents",
            json={"name": "durable-sender", "capabilities": ["x"]},
            headers=HEADERS,
        )
        r = await client.post(
            "/v1/comms/agents",
            json={"name": "durable-receiver", "capabilities": ["y"]},
            headers=HEADERS,
        )
        sender_id = s.json()["agent_id"]
        receiver_id = r.json()["agent_id"]

        send = await client.post(
            "/v1/agent-comms/send",
            json={
                "from_agent": sender_id,
                "to_agent": receiver_id,
                "subject": "hello",
                "body": {"k": "v"},
            },
            headers=HEADERS,
        )
        assert send.status_code == 202
        send_body = send.json()
        mid = send_body["message_id"]
        assert send_body["payload_hash"] is not None
        assert len(send_body["payload_hash"]) == 64

    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                select(AgentCommsMessageModel).where(
                    AgentCommsMessageModel.message_id == mid
                )
            )
        ).scalar_one_or_none()
    assert row is not None
    assert row.from_agent == sender_id
    assert row.to_agent == receiver_id
    assert row.payload_hash == send_body["payload_hash"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        inbox = await client.get(
            "/v1/agent-comms/inbox",
            params={"agent_id": receiver_id},
            headers=HEADERS,
        )
    assert inbox.status_code == 200
    data = inbox.json()
    assert data["total"] >= 1
    match = next(m for m in data["messages"] if m["message_id"] == mid)
    assert match["payload_hash"] == row.payload_hash
    assert match["delivered_at"] is not None


@pytest.mark.anyio
async def test_simulation_skips_db_row_for_send():
    settings = get_settings()
    settings.SIMULATION_MODE_AGENT_COMMS = True
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        s = await client.post(
            "/v1/comms/agents",
            json={"name": "sim-sender", "capabilities": ["x"]},
            headers=HEADERS,
        )
        r = await client.post(
            "/v1/comms/agents",
            json={"name": "sim-receiver", "capabilities": ["y"]},
            headers=HEADERS,
        )
        sender_id = s.json()["agent_id"]
        receiver_id = r.json()["agent_id"]
        send = await client.post(
            "/v1/agent-comms/send",
            json={
                "from_agent": sender_id,
                "to_agent": receiver_id,
                "subject": "hi",
                "body": {"a": 1},
            },
            headers=HEADERS,
        )
        assert send.status_code == 202
        assert send.json()["payload_hash"] is None
        mid = send.json()["message_id"]

    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                select(AgentCommsMessageModel).where(
                    AgentCommsMessageModel.message_id == mid
                )
            )
        ).scalar_one_or_none()
    assert row is None


@pytest.mark.anyio
async def test_durable_send_rejects_sender_owned_by_another_key():
    settings = get_settings()
    settings.SIMULATION_MODE_AGENT_COMMS = False
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers_a = await create_wallet_key(client, "durable-send-a")
        headers_b = await create_wallet_key(client, "durable-send-b")

        sender = await client.post(
            "/v1/comms/agents",
            json={"name": "durable-owned-sender", "capabilities": ["x"]},
            headers=headers_a,
        )
        receiver = await client.post(
            "/v1/comms/agents",
            json={"name": "durable-owned-receiver", "capabilities": ["y"]},
            headers=headers_b,
        )

        send = await client.post(
            "/v1/agent-comms/send",
            json={
                "from_agent": sender.json()["agent_id"],
                "to_agent": receiver.json()["agent_id"],
                "subject": "blocked",
                "body": {"blocked": True},
            },
            headers=headers_b,
        )

    assert send.status_code == 403
