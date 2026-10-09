"""Service-layer tests for app/services/iot_bridge.py.

Covers the protocol-translation core directly: the MQTT/CoAP translators
and the ProtocolBridge orchestrator (routing, ACL enforcement, error
paths). The registry itself is covered by test_iot_registry.py, the ACL
matrix by test_iot_acl.py, and the HTTP surface by test_iot.py.
"""

import pytest
from sqlalchemy import delete

from app.db.database import get_session_factory
from app.db.models import IoTDeviceEventModel, IoTDeviceModel
from app.schemas.iot import ACLPermission, ProtocolType
from app.services.iot_bridge import (
    ACLViolation,
    CoAPTranslator,
    DeviceRegistry,
    MQTTTranslator,
    ProtocolBridge,
    RegisteredDevice,
    TopicACLEngine,
    _row_to_device,
)


@pytest.fixture(autouse=True)
async def _clean_iot_tables():
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(delete(IoTDeviceEventModel))
        await session.execute(delete(IoTDeviceModel))
        await session.commit()
    yield


def _device(
    device_id: str = "bridge-dev-1",
    protocol: ProtocolType = ProtocolType.MQTT,
    acl: dict | None = None,
) -> RegisteredDevice:
    return RegisteredDevice(
        device_id=device_id,
        protocol=protocol,
        broker_url="mqtt://broker:1883",
        topic_acl=acl if acl is not None else {"device/+/command": ACLPermission.WRITE},
        metadata={"location": "lab"},
    )


def _bridge() -> ProtocolBridge:
    return ProtocolBridge(mqtt_broker_url="mqtt://broker:1883")


# ---------------------------------------------------------------------------
# ACL engine: deny-by-default edge
# ---------------------------------------------------------------------------


@pytest.mark.proof
@pytest.mark.parametrize("required", [ACLPermission.READ, ACLPermission.WRITE])
def test_empty_acl_denies_all(required):
    assert TopicACLEngine.check({}, "any/topic", required) is False


@pytest.mark.proof
def test_hash_wildcard_matches_nested_topic():
    assert TopicACLEngine.check(
        {"device/#": ACLPermission.READ}, "device/a/b/c", ACLPermission.READ
    )


@pytest.mark.proof
def test_read_write_satisfies_either_direction():
    acl = {"device/cmd": ACLPermission.READ_WRITE}
    assert TopicACLEngine.check(acl, "device/cmd", ACLPermission.READ)
    assert TopicACLEngine.check(acl, "device/cmd", ACLPermission.WRITE)


# ---------------------------------------------------------------------------
# Row conversion edge cases
# ---------------------------------------------------------------------------


@pytest.mark.proof
def test_row_to_device_tolerates_corrupt_json_and_unknown_values():
    row = IoTDeviceModel(
        device_id="broken-row",
        protocol="not-a-protocol",
        broker_url=None,
        topic_acl_json='{"ok/topic": "write", "bad/topic": "nonsense"',
        metadata_json="not json at all",
        status="registered",
    )
    device = _row_to_device(row)
    assert device.protocol == ProtocolType.MQTT
    assert device.topic_acl == {}
    assert device.metadata == {}
    assert device.owner_wallet_id is None


@pytest.mark.proof
def test_row_to_device_skips_unknown_permission_keeps_known():
    row = IoTDeviceModel(
        device_id="mixed-row",
        protocol="mqtt",
        broker_url=None,
        topic_acl_json='{"good/topic": "write", "weird/topic": "execute"}',
        metadata_json="{}",
        status="registered",
    )
    device = _row_to_device(row)
    assert device.topic_acl == {"good/topic": ACLPermission.WRITE}


# ---------------------------------------------------------------------------
# Translators (no database, no network)
# ---------------------------------------------------------------------------


@pytest.mark.proof
async def test_mqtt_connect_and_publish_dict_payload():
    translator = MQTTTranslator("mqtt://broker:1883")
    await translator.connect()
    response = await translator.publish("device/a/command", {"action": "ping"})
    assert response["ack"] is True
    assert response["topic"] == "device/a/command"
    assert response["qos"] == 1
    assert response["retained"] is False
    assert response["payload_size"] > 0


@pytest.mark.proof
async def test_mqtt_publish_str_payload_uses_explicit_qos_and_retain():
    translator = MQTTTranslator("mqtt://broker:1883", default_qos=1)
    response = await translator.publish("device/a/command", "raw", qos=2, retain=True)
    assert response["qos"] == 2
    assert response["retained"] is True
    assert response["payload_size"] == len(b"raw")


@pytest.mark.proof
async def test_mqtt_subscribe_returns_unique_ids():
    translator = MQTTTranslator("mqtt://broker:1883")
    first = await translator.subscribe("device/+/telemetry")
    second = await translator.subscribe("device/+/telemetry")
    assert first and second and first != second


@pytest.mark.proof
async def test_coap_get_and_put_round_trip():
    coap = CoAPTranslator()
    got = await coap.get("coap://device/sensor")
    assert got["status"] == "2.05"
    assert got["uri"] == "coap://device/sensor"
    put = await coap.put("coap://device/sensor", {"level": 3})
    assert put["status"] == "2.04"
    assert put["payload"] == {"level": 3}


# ---------------------------------------------------------------------------
# Bridge orchestrator
# ---------------------------------------------------------------------------


@pytest.mark.proof
async def test_bridge_initialize_connects():
    bridge = _bridge()
    await bridge.initialize()
    assert bridge.mqtt._connected is True


@pytest.mark.proof
async def test_bridge_send_mqtt_delivers_and_records_stats():
    bridge = _bridge()
    await bridge.registry.register(_device())
    message = await bridge.send_message(
        "bridge-dev-1", "device/room/command", {"action": "ping"}
    )
    assert message.status == "delivered"
    assert message.protocol == ProtocolType.MQTT
    assert message.native_response is not None
    assert message.native_response["ack"] is True

    stored = await bridge.registry.get("bridge-dev-1")
    assert stored is not None
    assert stored.message_count == 1
    assert stored.last_message_at is not None


@pytest.mark.proof
async def test_bridge_send_accepts_str_payload():
    bridge = _bridge()
    await bridge.registry.register(_device())
    message = await bridge.send_message("bridge-dev-1", "device/room/command", "raw")
    assert message.status == "delivered"
    assert message.payload == "raw"


@pytest.mark.proof
async def test_bridge_send_coap_routes_to_coap_translator():
    bridge = _bridge()
    await bridge.registry.register(
        _device(
            device_id="coap-dev",
            protocol=ProtocolType.COAP,
            acl={"sensors/temp": ACLPermission.WRITE},
        )
    )
    message = await bridge.send_message("coap-dev", "sensors/temp", {"level": 3})
    assert message.protocol == ProtocolType.COAP
    assert message.native_response is not None
    assert message.native_response["status"] == "2.04"


@pytest.mark.proof
async def test_bridge_send_unsupported_protocol_returns_simulated():
    bridge = _bridge()
    await bridge.registry.register(
        _device(
            device_id="zigbee-dev",
            protocol=ProtocolType.ZIGBEE,
            acl={"sensors/temp": ACLPermission.WRITE},
        )
    )
    message = await bridge.send_message("zigbee-dev", "sensors/temp", {"level": 1})
    assert message.status == "delivered"
    assert message.native_response is not None
    assert message.native_response["status"] == "simulated"


@pytest.mark.proof
async def test_bridge_send_unknown_device_raises_value_error():
    bridge = _bridge()
    with pytest.raises(ValueError, match="not found"):
        await bridge.send_message("ghost-device", "any/topic", {"a": 1})


@pytest.mark.proof
async def test_bridge_send_acl_violation_raises_and_records_event():
    bridge = _bridge()
    await bridge.registry.register(_device())
    with pytest.raises(ACLViolation):
        await bridge.send_message("bridge-dev-1", "device/room/camera", {"a": 1})
    events = await bridge.registry.recent_events(limit=10)
    assert any(
        e["event"] == "acl_violation"
        and e["device_id"] == "bridge-dev-1"
        and e.get("topic") == "device/room/camera"
        and e.get("action") == "write"
        for e in events
    )


@pytest.mark.proof
async def test_bridge_subscribe_returns_active_subscription():
    bridge = _bridge()
    device_id = "sub-dev"
    topic = "device/sub/telemetry"
    await bridge.registry.register(
        RegisteredDevice(
            device_id=device_id,
            protocol=ProtocolType.MQTT,
            broker_url=None,
            topic_acl={topic: ACLPermission.READ},
            metadata={},
        )
    )
    result = await bridge.subscribe(device_id, topic)
    assert result["status"] == "active"
    assert result["device_id"] == device_id
    assert result["topic"] == topic
    assert result["subscription_id"]


@pytest.mark.proof
async def test_bridge_subscribe_unknown_device_raises_value_error():
    bridge = _bridge()
    with pytest.raises(ValueError, match="not found"):
        await bridge.subscribe("ghost-device", "any/topic")


@pytest.mark.proof
async def test_bridge_subscribe_acl_violation_raises():
    bridge = _bridge()
    await bridge.registry.register(_device())
    with pytest.raises(ACLViolation):
        await bridge.subscribe("bridge-dev-1", "device/room/camera")


@pytest.mark.proof
async def test_bridge_audit_log_returns_recent_events_oldest_first():
    bridge = _bridge()
    registry = DeviceRegistry()
    await registry.register(_device(device_id="audit-dev"))
    await registry.record_event("audit-dev", "message_sent", topic="a")
    await registry.record_event("audit-dev", "message_sent", topic="b")
    entries = await bridge.get_audit_log(limit=2)
    assert [e.get("topic") for e in entries] == ["a", "b"]
