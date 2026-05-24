from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.dependencies import get_agent_comms
from app.core.runtime_mode import is_simulation
from app.schemas.billing import ServiceCategory
from app.services.agent_comms import MessagePriority, MessageType
from app.services.agent_comms_store import compute_payload_hash
from app.services.service_registry import get_service_registry

PAID_PILOT_AGENT_COMMS_TOOL = "agent-comms-send"
PAID_PILOT_AGENT_COMMS_PRICE = 2.0


class AgentCommsSendToolInput(BaseModel):
    to_agent: str = Field(..., description="Recipient agent id")
    subject: str = Field(..., description="Message subject")
    body: dict[str, Any] = Field(default_factory=dict, description="Message body")
    message_type: MessageType = MessageType.REQUEST
    priority: MessagePriority = MessagePriority.NORMAL
    correlation_id: str | None = None
    reply_to: str | None = None


class AgentCommsSendToolOutput(BaseModel):
    message_id: str
    from_agent: str
    to_agent: str
    status: str
    payload_hash: str | None = None
    durable: bool


async def agent_comms_send_tool(
    *,
    to_agent: str,
    subject: str,
    body: dict[str, Any] | None = None,
    message_type: str | MessageType = MessageType.REQUEST,
    priority: str | MessagePriority = MessagePriority.NORMAL,
    correlation_id: str | None = None,
    reply_to: str | None = None,
    _mcp_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = _mcp_context or {}
    wallet_id = str(context.get("wallet_id") or "")
    if not wallet_id:
        raise ValueError("missing_governed_wallet_context")

    msg = await get_agent_comms().send_message(
        from_agent=wallet_id,
        to_agent=to_agent,
        message_type=MessageType(message_type),
        subject=subject,
        body=body or {},
        priority=MessagePriority(priority),
        correlation_id=correlation_id,
        reply_to=reply_to,
    )

    payload_hash = compute_payload_hash(
        body=msg.body,
        correlation_id=msg.correlation_id,
        from_agent=msg.from_agent,
        message_type=msg.message_type.value,
        priority=msg.priority.value,
        reply_to=msg.reply_to,
        subject=msg.subject,
        to_agent=msg.to_agent,
    )

    return {
        "message_id": msg.message_id,
        "from_agent": msg.from_agent,
        "to_agent": msg.to_agent,
        "status": msg.delivery_status.value,
        "payload_hash": payload_hash,
        "durable": True,
    }


def sync_paid_pilot_mcp_tools() -> None:
    registry = get_service_registry()
    if is_simulation("agent_comms"):
        registry.unregister_local(PAID_PILOT_AGENT_COMMS_TOOL)
        return

    if registry.get_local(PAID_PILOT_AGENT_COMMS_TOOL):
        return

    registry.register_local(
        service_id=PAID_PILOT_AGENT_COMMS_TOOL,
        name="Agent Comms Send",
        description=(
            "Send a durable SQL-backed agent communication through the governed "
            "MCP trust plane."
        ),
        category=ServiceCategory.AGENT_COMMS,
        func=agent_comms_send_tool,
        input_model=AgentCommsSendToolInput,
        output_model=AgentCommsSendToolOutput,
        credits_per_unit=PAID_PILOT_AGENT_COMMS_PRICE,
        unit_name="message",
    )
