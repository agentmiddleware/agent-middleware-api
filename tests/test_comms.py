"""
Tests for the Agent Communications endpoints.
Validates agent registration, messaging, polling, and capability-based handoffs.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def api_headers():
    return {"X-API-Key": "test-key"}


async def create_wallet_key(client, api_headers, name):
    wallet_resp = await client.post(
        "/v1/billing/wallets/sponsor",
        json={"sponsor_name": name, "email": f"{name}@test.example"},
        headers=api_headers,
    )
    assert wallet_resp.status_code == 201
    wallet_id = wallet_resp.json()["wallet_id"]

    key_resp = await client.post(
        "/v1/api-keys",
        json={"wallet_id": wallet_id, "key_name": name},
        headers=api_headers,
    )
    assert key_resp.status_code == 201
    return {"X-API-Key": key_resp.json()["api_key"]}


# --- Agent Registration ---

@pytest.mark.anyio
async def test_register_agent(client, api_headers):
    resp = await client.post(
        "/v1/comms/agents",
        json={
            "name": "test-iot-agent",
            "capabilities": ["iot-monitoring", "mqtt-bridging"],
            "webhook_url": "https://my-agent.example.com/webhook",
        },
        headers=api_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "agent_id" in data
    assert data["name"] == "test-iot-agent"
    assert "api_key" in data
    assert data["capabilities"] == ["iot-monitoring", "mqtt-bridging"]


@pytest.mark.anyio
async def test_list_agents(client, api_headers):
    await client.post(
        "/v1/comms/agents",
        json={"name": "list-test", "capabilities": ["testing"]},
        headers=api_headers,
    )
    resp = await client.get("/v1/comms/agents", headers=api_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


@pytest.mark.anyio
async def test_filter_agents_by_capability(client, api_headers):
    await client.post(
        "/v1/comms/agents",
        json={"name": "video-agent", "capabilities": ["video-transcription"]},
        headers=api_headers,
    )
    resp = await client.get(
        "/v1/comms/agents?capability=video-transcription",
        headers=api_headers,
    )
    assert resp.status_code == 200
    agents = resp.json()["agents"]
    assert all("video-transcription" in a["capabilities"] for a in agents)


# --- Messaging ---

@pytest.mark.anyio
async def test_send_message(client, api_headers):
    # Register sender and receiver
    sender = await client.post(
        "/v1/comms/agents",
        json={"name": "sender", "capabilities": ["sending"]},
        headers=api_headers,
    )
    receiver = await client.post(
        "/v1/comms/agents",
        json={"name": "receiver", "capabilities": ["receiving"]},
        headers=api_headers,
    )

    sender_id = sender.json()["agent_id"]
    receiver_id = receiver.json()["agent_id"]

    resp = await client.post(
        f"/v1/comms/messages?from_agent={sender_id}",
        json={
            "to_agent": receiver_id,
            "message_type": "request",
            "subject": "Process this data",
            "body": {"data_id": "xyz-123"},
        },
        headers=api_headers,
    )
    assert resp.status_code == 202
    assert resp.json()["from_agent"] == sender_id
    assert resp.json()["to_agent"] == receiver_id


@pytest.mark.anyio
async def test_poll_inbox(client, api_headers):
    # Register and send
    reg = await client.post(
        "/v1/comms/agents",
        json={"name": "poller", "capabilities": ["polling"]},
        headers=api_headers,
    )
    agent_id = reg.json()["agent_id"]

    resp = await client.get(
        f"/v1/comms/messages/{agent_id}/inbox",
        headers=api_headers,
    )
    assert resp.status_code == 200
    assert "messages" in resp.json()


# --- Handoff ---

@pytest.mark.anyio
async def test_handoff_no_agent_found(client, api_headers):
    sender = await client.post(
        "/v1/comms/agents",
        json={"name": "handoff-requester-no-match", "capabilities": ["requesting"]},
        headers=api_headers,
    )
    sender_id = sender.json()["agent_id"]

    resp = await client.post(
        f"/v1/comms/handoff?from_agent={sender_id}",
        json={
            "capability": "nonexistent-capability",
            "context": {"task": "impossible"},
        },
        headers=api_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "no_agent_found"


@pytest.mark.anyio
async def test_handoff_with_matching_agent(client, api_headers):
    sender = await client.post(
        "/v1/comms/agents",
        json={"name": "handoff-requester", "capabilities": ["requesting"]},
        headers=api_headers,
    )
    sender_id = sender.json()["agent_id"]

    # Register specialist
    await client.post(
        "/v1/comms/agents",
        json={"name": "transcriber", "capabilities": ["transcription"]},
        headers=api_headers,
    )

    resp = await client.post(
        f"/v1/comms/handoff?from_agent={sender_id}",
        json={
            "capability": "transcription",
            "context": {"video_id": "abc-123"},
        },
        headers=api_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "handoff_sent"
    assert resp.json()["target_agent_name"] == "transcriber"


@pytest.mark.anyio
async def test_db_key_cannot_send_as_agent_owned_by_another_key(client, api_headers):
    headers_a = await create_wallet_key(client, api_headers, "comms-send-a")
    headers_b = await create_wallet_key(client, api_headers, "comms-send-b")

    sender = await client.post(
        "/v1/comms/agents",
        json={"name": "owned-sender", "capabilities": ["sending"]},
        headers=headers_a,
    )
    receiver = await client.post(
        "/v1/comms/agents",
        json={"name": "owned-receiver", "capabilities": ["receiving"]},
        headers=headers_b,
    )

    resp = await client.post(
        f"/v1/comms/messages?from_agent={sender.json()['agent_id']}",
        json={
            "to_agent": receiver.json()["agent_id"],
            "message_type": "request",
            "subject": "Impersonated send",
            "body": {"blocked": True},
        },
        headers=headers_b,
    )

    assert resp.status_code == 403


@pytest.mark.anyio
async def test_db_key_cannot_handoff_as_agent_owned_by_another_key(client, api_headers):
    headers_a = await create_wallet_key(client, api_headers, "comms-handoff-a")
    headers_b = await create_wallet_key(client, api_headers, "comms-handoff-b")

    sender = await client.post(
        "/v1/comms/agents",
        json={"name": "owned-handoff-sender", "capabilities": ["requesting"]},
        headers=headers_a,
    )
    await client.post(
        "/v1/comms/agents",
        json={"name": "handoff-specialist", "capabilities": ["blocked-capability"]},
        headers=headers_b,
    )

    resp = await client.post(
        f"/v1/comms/handoff?from_agent={sender.json()['agent_id']}",
        json={
            "capability": "blocked-capability",
            "context": {"blocked": True},
        },
        headers=headers_b,
    )

    assert resp.status_code == 403


@pytest.mark.anyio
async def test_db_key_cannot_ack_agent_inbox_owned_by_another_key(client, api_headers):
    headers_a = await create_wallet_key(client, api_headers, "comms-ack-a")
    headers_b = await create_wallet_key(client, api_headers, "comms-ack-b")

    sender = await client.post(
        "/v1/comms/agents",
        json={"name": "ack-sender", "capabilities": ["sending"]},
        headers=headers_a,
    )
    receiver = await client.post(
        "/v1/comms/agents",
        json={"name": "ack-receiver", "capabilities": ["receiving"]},
        headers=headers_a,
    )
    message = await client.post(
        f"/v1/comms/messages?from_agent={sender.json()['agent_id']}",
        json={
            "to_agent": receiver.json()["agent_id"],
            "message_type": "request",
            "subject": "Needs ack",
            "body": {"ok": True},
        },
        headers=headers_a,
    )
    assert message.status_code == 202

    resp = await client.post(
        (
            f"/v1/comms/messages/{receiver.json()['agent_id']}/ack/"
            f"{message.json()['message_id']}"
        ),
        headers=headers_b,
    )

    assert resp.status_code == 403
