"""
Tests for the IoT Protocol Bridge endpoints.
Validates device registration, ACL enforcement, and message bridging.
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


@pytest.fixture
def sample_device():
    return {
        "device_id": "test-sensor-001",
        "protocol": "mqtt",
        "topic_acl": {
            "device/+/telemetry": "read",
            "device/+/command": "write",
            "device/+/camera": "deny",
        },
        "metadata": {"location": "warehouse-A"},
    }


# --- Device Registration ---

@pytest.mark.anyio
async def test_register_device(client, api_headers, sample_device):
    resp = await client.post("/v1/iot/devices", json=sample_device, headers=api_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["device_id"] == "test-sensor-001"
    assert data["protocol"] == "mqtt"
    assert data["status"] == "registered"
    assert "/messages" in data["bridge_endpoint"]


@pytest.mark.anyio
async def test_register_duplicate_device(client, api_headers, sample_device):
    # First registration
    await client.post("/v1/iot/devices", json=sample_device, headers=api_headers)
    # Duplicate should fail
    resp = await client.post("/v1/iot/devices", json=sample_device, headers=api_headers)
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "device_exists"


@pytest.mark.anyio
async def test_list_devices(client, api_headers, sample_device):
    await client.post("/v1/iot/devices", json=sample_device, headers=api_headers)
    resp = await client.get("/v1/iot/devices", headers=api_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert len(data["devices"]) >= 1


@pytest.mark.anyio
async def test_get_device(client, api_headers, sample_device):
    await client.post("/v1/iot/devices", json=sample_device, headers=api_headers)
    resp = await client.get(f"/v1/iot/devices/{sample_device['device_id']}", headers=api_headers)
    assert resp.status_code == 200
    assert resp.json()["device_id"] == sample_device["device_id"]


@pytest.mark.anyio
async def test_get_nonexistent_device(client, api_headers):
    resp = await client.get("/v1/iot/devices/nonexistent", headers=api_headers)
    assert resp.status_code == 404


# --- Message Sending with ACL ---

@pytest.mark.anyio
async def test_send_message_allowed_topic(client, api_headers, sample_device):
    await client.post("/v1/iot/devices", json=sample_device, headers=api_headers)
    msg = {
        "topic": "device/test-sensor-001/command",
        "payload": {"action": "report_status"},
        "qos": 1,
    }
    resp = await client.post(
        f"/v1/iot/devices/{sample_device['device_id']}/messages",
        json=msg,
        headers=api_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "delivered"


@pytest.mark.anyio
async def test_send_message_denied_topic(client, api_headers, sample_device):
    await client.post("/v1/iot/devices", json=sample_device, headers=api_headers)
    msg = {
        "topic": "device/test-sensor-001/camera",
        "payload": {"action": "stream"},
        "qos": 1,
    }
    resp = await client.post(
        f"/v1/iot/devices/{sample_device['device_id']}/messages",
        json=msg,
        headers=api_headers,
    )
    assert resp.status_code == 403
    assert "acl" in resp.json()["detail"]["error"]


@pytest.mark.anyio
async def test_send_message_empty_acl_denies_all(client, api_headers):
    device = {
        "device_id": "locked-device",
        "protocol": "mqtt",
        "topic_acl": {},
    }
    await client.post("/v1/iot/devices", json=device, headers=api_headers)
    msg = {"topic": "any/topic", "payload": "test"}
    resp = await client.post(
        "/v1/iot/devices/locked-device/messages",
        json=msg,
        headers=api_headers,
    )
    assert resp.status_code == 403


# --- Auth ---

@pytest.mark.anyio
async def test_missing_api_key(client):
    resp = await client.get("/v1/iot/devices")
    assert resp.status_code == 401
