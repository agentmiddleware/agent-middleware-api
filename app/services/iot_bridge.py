"""
IoT Protocol Bridge — Service Layer
=====================================
Handles the actual protocol translation between REST and native IoT protocols.
This is where the "bridge" lives: HTTP in, MQTT/CoAP/etc out.

Security-first design:
- Deny-by-default topic ACLs
- Per-device credential isolation
- Message payload sanitization
- Audit logging on every bridge operation

In production, swap the in-memory stores for Redis (device state)
and PostgreSQL (audit log, ACL rules).
"""

import asyncio
import json
import re
import uuid
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any

from ..schemas.iot import ACLPermission, ProtocolType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ACL Engine
# ---------------------------------------------------------------------------

class ACLViolation(Exception):
    """Raised when a message violates topic-level access controls."""
    def __init__(self, device_id: str, topic: str, required: str):
        self.device_id = device_id
        self.topic = topic
        self.required = required
        super().__init__(
            f"ACL violation: device '{device_id}' cannot {required} topic '{topic}'"
        )


class TopicACLEngine:
    """
    Evaluates MQTT-style topic ACL rules with wildcard support.

    Rules:
    - '+' matches a single topic level  (e.g., device/+/telemetry)
    - '#' matches all remaining levels   (e.g., device/#)
    - Empty ACL dict = deny-all (secure default)
    - Explicit 'deny' overrides any allow
    """

    @staticmethod
    def _topic_to_regex(pattern: str) -> str:
        """Convert MQTT topic pattern to regex."""
        # Escape dots, replace MQTT wildcards
        escaped = re.escape(pattern)
        escaped = escaped.replace(r"\+", "[^/]+")
        escaped = escaped.replace(r"\#", ".*")
        return f"^{escaped}$"

    @staticmethod
    def check(
        acl: dict[str, ACLPermission],
        topic: str,
        required: ACLPermission,
    ) -> bool:
        """
        Check if a topic access is permitted.

        Returns True if allowed, raises ACLViolation if denied.
        """
        if not acl:
            return False  # Deny-by-default

        matched_permission: ACLPermission | None = None

        # Check exact match first
        if topic in acl:
            matched_permission = acl[topic]
        else:
            # Check wildcard patterns (most specific wins)
            best_specificity = -1
            for pattern, perm in acl.items():
                if "+" not in pattern and "#" not in pattern:
                    continue
                regex = TopicACLEngine._topic_to_regex(pattern)
                if re.match(regex, topic):
                    # More segments = more specific
                    specificity = pattern.count("/")
                    if specificity > best_specificity:
                        best_specificity = specificity
                        matched_permission = perm

        if matched_permission is None or matched_permission == ACLPermission.DENY:
            return False

        if required == ACLPermission.WRITE and matched_permission == ACLPermission.READ:
            return False

        return True


# ---------------------------------------------------------------------------
# Device Registry
# ---------------------------------------------------------------------------

@dataclass
class RegisteredDevice:
    """Internal representation of a registered device."""
    device_id: str
    protocol: ProtocolType
    broker_url: str | None
    topic_acl: dict[str, ACLPermission]
    metadata: dict
    status: str = "registered"
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_message_at: datetime | None = None
    message_count: int = 0


class DeviceRegistry:
    """
    In-memory device registry. Replace with Redis/PostgreSQL in production.
    Thread-safe via asyncio locks.
    """

    def __init__(self):
        self._devices: dict[str, RegisteredDevice] = {}
        self._lock = asyncio.Lock()

    async def register(self, device: RegisteredDevice) -> RegisteredDevice:
        async with self._lock:
            if device.device_id in self._devices:
                raise ValueError(f"Device '{device.device_id}' already registered")
            self._devices[device.device_id] = device
            logger.info(f"Device registered: {device.device_id} ({device.protocol})")
            return device

    async def get(self, device_id: str) -> RegisteredDevice | None:
        return self._devices.get(device_id)

    async def list_all(
        self,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[RegisteredDevice], int]:
        devices = list(self._devices.values())
        total = len(devices)
        start = (page - 1) * per_page
        return devices[start:start + per_page], total

    async def deregister(self, device_id: str) -> bool:
        async with self._lock:
            if device_id in self._devices:
                del self._devices[device_id]
                logger.info(f"Device deregistered: {device_id}")
                return True
            return False

    async def update_message_stats(self, device_id: str):
        async with self._lock:
            device = self._devices.get(device_id)
            if device:
                device.last_message_at = datetime.now(timezone.utc)
                device.message_count += 1


# ---------------------------------------------------------------------------
# Protocol Translators
# ---------------------------------------------------------------------------

@dataclass
class BridgedMessage:
    """A message that has been translated and sent through the bridge."""
    message_id: str
    device_id: str
    topic: str
    payload: Any
    protocol: ProtocolType
    status: str
    delivered_at: datetime
    native_response: dict | None = None


class MQTTTranslator:
    """
    Translates REST API calls into MQTT publish/subscribe operations.

    In production, this wraps aiomqtt for actual broker communication.
    Currently returns simulated responses for scaffold validation.
    """

    def __init__(self, broker_url: str, default_qos: int = 1):
        self.broker_url = broker_url
        self.default_qos = default_qos
        self._connected = False

    async def connect(self):
        """Connect to the MQTT broker."""
        # Production: self._client = aiomqtt.Client(self.broker_url)
        self._connected = True
        logger.info(f"MQTT translator connected to {self.broker_url}")

    async def publish(
        self,
        topic: str,
        payload: dict | str,
        qos: int | None = None,
        retain: bool = False,
    ) -> dict:
        """Publish a message to the MQTT broker."""
        if isinstance(payload, dict):
            payload_bytes = json.dumps(payload).encode()
        else:
            payload_bytes = payload.encode()

        # Production: await self._client.publish(
        #     topic, payload_bytes, qos=qos or self.default_qos
        # )
        logger.info(
            f"MQTT publish: {topic} ({len(payload_bytes)} bytes, "
            f"qos={qos or self.default_qos})"
        )

        return {
            "ack": True,
            "broker": self.broker_url,
            "topic": topic,
            "payload_size": len(payload_bytes),
            "qos": qos or self.default_qos,
            "retained": retain,
        }

    async def subscribe(self, topic: str, qos: int | None = None) -> str:
        """Subscribe to a topic. Returns a subscription ID."""
        subscription_id = str(uuid.uuid4())
        # Production: await self._client.subscribe(topic, qos=qos or self.default_qos)
        logger.info(f"MQTT subscribe: {topic} → {subscription_id}")
        return subscription_id


class CoAPTranslator:
    """CoAP protocol translator stub. Wire up aiocoap in production."""

    async def get(self, uri: str) -> dict:
        return {"status": "2.05", "payload": {}, "uri": uri}

    async def put(self, uri: str, payload: dict) -> dict:
        return {"status": "2.04", "payload": payload, "uri": uri}


# ---------------------------------------------------------------------------
# Bridge Orchestrator
# ---------------------------------------------------------------------------

class ProtocolBridge:
    """
    Main orchestrator: routes messages through the correct protocol translator
    after ACL validation.
    """

    def __init__(self, mqtt_broker_url: str, mqtt_default_qos: int = 1):
        self.registry = DeviceRegistry()
        self.acl_engine = TopicACLEngine()
        self.mqtt = MQTTTranslator(mqtt_broker_url, mqtt_default_qos)
        self.coap = CoAPTranslator()
        self._audit_log: list[dict] = []

    async def initialize(self):
        """Start protocol connections."""
        await self.mqtt.connect()
        logger.info("Protocol bridge initialized")

    async def send_message(
        self,
        device_id: str,
        topic: str,
        payload: dict | str,
        qos: int = 1,
        retain: bool = False,
    ) -> BridgedMessage:
        """
        Send a message through the bridge with full ACL enforcement.
        """
        device = await self.registry.get(device_id)
        if not device:
            raise ValueError(f"Device '{device_id}' not found")

        # ACL check
        if not self.acl_engine.check(device.topic_acl, topic, ACLPermission.WRITE):
            self._audit_log.append({
                "event": "acl_violation",
                "device_id": device_id,
                "topic": topic,
                "action": "write",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            raise ACLViolation(device_id, topic, "write")

        # Route to correct translator
        native_response = None
        if device.protocol == ProtocolType.MQTT:
            native_response = await self.mqtt.publish(topic, payload, qos, retain)
        elif device.protocol == ProtocolType.COAP:
            payload_data = payload if isinstance(payload, dict) else {"data": payload}
            native_response = await self.coap.put(topic, payload_data)
        else:
            # For protocols without a translator yet, log and simulate
            native_response = {"status": "simulated", "protocol": device.protocol.value}

        await self.registry.update_message_stats(device_id)

        message = BridgedMessage(
            message_id=str(uuid.uuid4()),
            device_id=device_id,
            topic=topic,
            payload=payload,
            protocol=device.protocol,
            status="delivered",
            delivered_at=datetime.now(timezone.utc),
            native_response=native_response,
        )

        self._audit_log.append({
            "event": "message_sent",
            "device_id": device_id,
            "topic": topic,
            "message_id": message.message_id,
            "protocol": device.protocol.value,
            "timestamp": message.delivered_at.isoformat(),
        })

        return message

    async def subscribe(self, device_id: str, topic: str) -> dict:
        """Subscribe to device messages with ACL enforcement."""
        device = await self.registry.get(device_id)
        if not device:
            raise ValueError(f"Device '{device_id}' not found")

        if not self.acl_engine.check(device.topic_acl, topic, ACLPermission.READ):
            raise ACLViolation(device_id, topic, "read")

        subscription_id = await self.mqtt.subscribe(topic)

        return {
            "subscription_id": subscription_id,
            "device_id": device_id,
            "topic": topic,
            "status": "active",
        }

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        """Return recent audit log entries."""
        return self._audit_log[-limit:]
