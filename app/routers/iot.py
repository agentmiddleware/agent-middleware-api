"""
IoT Protocol Bridge Router
--------------------------
Secure, topic-ACL-enforced protocol bridging for IoT devices.
Wired to ProtocolBridge service via FastAPI dependency injection.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..core.auth import verify_api_key
from ..core.dependencies import get_iot_bridge
from ..services.iot_bridge import ProtocolBridge, ACLViolation, RegisteredDevice
from ..schemas.iot import (
    DeviceRegistration,
    DeviceResponse,
    DeviceListResponse,
    BridgeMessage,
    BridgeMessageResponse,
)

router = APIRouter(
    prefix="/v1/iot",
    tags=["IoT Protocol Bridge"],
    dependencies=[Depends(verify_api_key)],
    responses={
        401: {"description": "Missing API key"},
        403: {"description": "Invalid API key or topic ACL violation"},
    },
)


def _device_to_response(device: RegisteredDevice) -> DeviceResponse:
    """Convert internal device to API response."""
    return DeviceResponse(
        device_id=device.device_id,
        protocol=device.protocol,
        bridge_endpoint=f"/v1/iot/devices/{device.device_id}/messages",
        topic_acl=device.topic_acl,
        status=device.status,
        registered_at=device.registered_at,
    )


@router.post(
    "/devices",
    response_model=DeviceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new IoT device",
    description=(
        "Register a device for protocol bridging. The device will receive a "
        "unified REST endpoint that translates HTTP requests into the device's "
        "native protocol. Topic ACLs are enforced on every message. "
        "An empty ACL dict defaults to deny-all for maximum security."
    ),
)
async def register_device(
    device: DeviceRegistration,
    bridge: ProtocolBridge = Depends(get_iot_bridge),
):
    existing = await bridge.registry.get(device.device_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "device_exists",
                "message": f"Device '{device.device_id}' is already registered.",
            },
        )

    registered = await bridge.registry.register(
        RegisteredDevice(
            device_id=device.device_id,
            protocol=device.protocol,
            broker_url=device.broker_url,
            topic_acl=device.topic_acl,
            metadata=device.metadata,
        )
    )
    return _device_to_response(registered)


@router.get(
    "/devices",
    response_model=DeviceListResponse,
    summary="List registered devices",
    description="Paginated listing of all devices registered to your API key.",
)
async def list_devices(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=200, description="Items per page"),
    bridge: ProtocolBridge = Depends(get_iot_bridge),
):
    devices, total = await bridge.registry.list_all(page, per_page)
    return DeviceListResponse(
        devices=[_device_to_response(d) for d in devices],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get(
    "/devices/{device_id}",
    response_model=DeviceResponse,
    summary="Get device details",
    description=(
        "Retrieve registration details and bridge endpoint for a specific device."
    ),
)
async def get_device(
    device_id: str,
    bridge: ProtocolBridge = Depends(get_iot_bridge),
):
    device = await bridge.registry.get(device_id)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "device_not_found",
                "message": f"Device '{device_id}' not found.",
            },
        )
    return _device_to_response(device)


@router.delete(
    "/devices/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deregister a device",
    description=(
        "Remove a device from the bridge. All pending messages will be dropped."
    ),
)
async def deregister_device(
    device_id: str,
    bridge: ProtocolBridge = Depends(get_iot_bridge),
):
    removed = await bridge.registry.deregister(device_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "device_not_found",
                "message": f"Device '{device_id}' not found.",
            },
        )


@router.post(
    "/devices/{device_id}/messages",
    response_model=BridgeMessageResponse,
    summary="Send a message to a device",
    description=(
        "Send a message through the protocol bridge to the device's native protocol. "
        "The topic must match an allowed ACL pattern. Messages to denied topics "
        "(e.g., camera feeds) will be rejected with a 403."
    ),
)
async def send_message(
    device_id: str,
    message: BridgeMessage,
    bridge: ProtocolBridge = Depends(get_iot_bridge),
):
    try:
        result = await bridge.send_message(
            device_id=device_id,
            topic=message.topic,
            payload=message.payload,
            qos=message.qos,
            retain=message.retain,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "device_not_found", "message": str(e)},
        )
    except ACLViolation as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "acl_denied", "message": str(e)},
        )

    return BridgeMessageResponse(
        message_id=result.message_id,
        device_id=result.device_id,
        topic=result.topic,
        status=result.status,
        delivered_at=result.delivered_at,
        protocol_native_response=result.native_response,
    )


@router.post(
    "/devices/{device_id}/subscribe",
    summary="Subscribe to device messages",
    description=(
        "Subscribe to messages from a device topic. Returns a webhook URL "
        "or WebSocket endpoint that agents can poll for incoming data. "
        "Topic must have READ permission in the device's ACL."
    ),
)
async def subscribe_to_device(
    device_id: str,
    topic: str,
    bridge: ProtocolBridge = Depends(get_iot_bridge),
):
    try:
        result = await bridge.subscribe(device_id, topic)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "device_not_found", "message": str(e)},
        )
    except ACLViolation as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "acl_denied", "message": str(e)},
        )

    return {
        **result,
        "webhook_url": f"/v1/iot/subscriptions/{result['subscription_id']}/poll",
        "websocket_url": f"ws://api.yourdomain.com/v1/iot/subscriptions/{result['subscription_id']}/ws",
    }
