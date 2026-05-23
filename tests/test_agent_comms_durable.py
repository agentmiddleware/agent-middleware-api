"""Contract: durable agent comms (DB + /v1/agent-comms)."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db.database import get_session_factory
from app.db.models import AgentCommsMessageModel
from app.main import app

HEADERS = {"X-API-Key": "test-key"}


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
async def test_durable_send_denied_when_caller_does_not_own_from_agent():
    """Authenticated callers cannot impersonate an agent they do not own on
    the durable send path."""
    from app.core.dependencies import get_agent_comms

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        sender = await client.post(
            "/v1/comms/agents",
            json={"name": "durable-foreign-sender", "capabilities": ["x"]},
            headers=HEADERS,
        )
        sender_id = sender.json()["agent_id"]
        # Rewrite owner_key so test-key no longer owns this agent.
        comms = get_agent_comms()
        agent = await comms.registry.get(sender_id)
        agent.owner_key = "owner-from-some-other-tenant-key"

        receiver = await client.post(
            "/v1/comms/agents",
            json={"name": "durable-foreign-receiver", "capabilities": ["y"]},
            headers=HEADERS,
        )
        receiver_id = receiver.json()["agent_id"]

        resp = await client.post(
            "/v1/agent-comms/send",
            json={
                "from_agent": sender_id,
                "to_agent": receiver_id,
                "subject": "spoof",
                "body": {"a": 1},
            },
            headers=HEADERS,
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["error"] == "access_denied"
